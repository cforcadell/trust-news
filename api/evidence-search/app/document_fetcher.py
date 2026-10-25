import asyncio
import json
import os
import random
import ipaddress
import re
import socket
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from io import BytesIO
from itertools import islice
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover - service image installs beautifulsoup4.
    BeautifulSoup = None

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - dependency is installed in the service image.
    PdfReader = None


HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")
PDF_CONTENT_TYPES = ("application/pdf", "application/x-pdf")
TEXT_CONTENT_TYPES = ("text/plain", "text/csv", "application/json", "application/xml", "text/xml")
# Select the document container before removing descendants.  Some official
# sites wrap the complete page in a form (ASP.NET) or expose malformed markup
# where ``main`` is parsed below ``header``.  Removing those structural tags
# from the whole soup can therefore delete the evidence itself.
REMOVE_SELECTORS = (
    "script", "style", "noscript", "svg", "template", "canvas",
    "input", "button", "select", "textarea",
)
CONTAINER_SELECTORS = ("article", "main", '[role="main"]')
PDF_MAX_BYTES = 15 * 1024 * 1024
MAX_REDIRECTS = 5
PDF_MAX_PAGES = int(os.getenv("EVIDENCE_PDF_MAX_PAGES", "80"))
FETCH_MAX_ATTEMPTS = max(1, int(os.getenv("EVIDENCE_FETCH_MAX_ATTEMPTS", "2")))
FETCH_RETRY_BASE_SECONDS = max(0.0, float(os.getenv("EVIDENCE_FETCH_RETRY_BASE_SECONDS", "0.5")))
FETCH_RETRY_MAX_SECONDS = max(
    FETCH_RETRY_BASE_SECONDS,
    float(os.getenv("EVIDENCE_FETCH_RETRY_MAX_SECONDS", "3")),
)
FETCH_RETRY_JITTER_RATIO = min(
    1.0, max(0.0, float(os.getenv("EVIDENCE_FETCH_RETRY_JITTER_RATIO", "0.2"))),
)
FETCH_RETRY_BUDGET_SECONDS = max(
    0.0, float(os.getenv("EVIDENCE_FETCH_RETRY_BUDGET_SECONDS", "15")),
)
RETRYABLE_OUTCOMES = {"PENDING", "RATE_LIMITED", "SERVER_FAILURE", "NETWORK_FAILURE"}
BLOCK_PAGE_MARKERS = (
    "access denied", "captcha", "checking your browser", "enable javascript",
    "just a moment", "too many requests", "verify you are human",
)


@dataclass
class FetchResult:
    status: str
    text: str = ""
    error: Optional[str] = None
    content_type: Optional[str] = None
    # Keep the URL returned by search separate from the URL that was actually
    # fetched.  A server can have a broken certificate on one hostname while a
    # verified, canonical www variant is available.
    fetched_url: Optional[str] = None
    url_normalized: bool = False
    normalization_reason: Optional[str] = None
    attempted_urls: Optional[List[str]] = None
    failure_stage: Optional[str] = None
    failure_code: Optional[str] = None
    retryable: bool = False
    http_status: Optional[int] = None
    response_bytes: int = 0
    detected_format: Optional[str] = None
    extractor: Optional[str] = None
    attempts: Optional[List[dict]] = None
    retry_after_seconds: Optional[float] = None
    retry_trace: Optional[List[dict]] = None

    @property
    def document_length_chars(self) -> int:
        return len(self.text)

    @property
    def outcome(self) -> str:
        """Return the stable, transport-independent fetch classification."""
        return classify_fetch_outcome(
            status=self.status,
            failure_code=self.failure_code,
            http_status=self.http_status,
        )

    @property
    def diagnostics(self) -> dict:
        """Expose additive diagnostics without changing the legacy status contract."""
        return {
            "outcome": self.outcome,
            "stage": self.failure_stage or ("COMPLETE" if self.status == "ok" else "FETCH"),
            "retryable": bool(self.retryable),
            "http_response_received": self.http_status is not None,
            "http_success": self.http_status is not None and 200 <= self.http_status < 300,
            "extracted": self.status == "ok",
            "retry_count": sum(action.get("action") == "RETRY" for action in self.retry_trace or []),
        }


def classify_fetch_outcome(*, status: str, failure_code: Optional[str],
                           http_status: Optional[int]) -> str:
    """Map legacy fetch details to a small, stable operational taxonomy."""
    if status == "ok":
        return "EXTRACTED"
    if failure_code == "HTTP_202_EMPTY_BODY":
        return "PENDING"
    if http_status in {401, 403} or failure_code == "BLOCK_PAGE":
        return "ACCESS_DENIED"
    if http_status in {404, 410}:
        return "NOT_FOUND"
    if http_status == 429 or failure_code == "HTTP_RATE_LIMITED":
        return "RATE_LIMITED"
    if (http_status is not None and http_status >= 500) or failure_code == "HTTP_SERVER_ERROR":
        return "SERVER_FAILURE"
    if failure_code in {"TIMEOUT", "NETWORK_ERROR", "TLS_HOSTNAME_MISMATCH"}:
        return "NETWORK_FAILURE"
    if failure_code in {"BODY_EMPTY", "HTML_NO_MAIN_CONTENT", "PDF_NO_TEXT"}:
        return "EMPTY_CONTENT"
    if failure_code == "FORMAT_UNSUPPORTED":
        return "UNSUPPORTED_CONTENT"
    if failure_code in {"EXTRACTOR_ERROR", "DOCUMENT_TOO_LARGE"}:
        return "EXTRACTION_FAILURE"
    if http_status is not None and 400 <= http_status < 500:
        return "CLIENT_FAILURE"
    return "FETCH_FAILURE"


def classify_attempt_outcome(attempt: dict) -> str:
    """Classify one recorded HTTP/network attempt using the same taxonomy."""
    raw = str(attempt.get("outcome") or "")
    status = attempt.get("http_status")
    legacy_status = "ok" if raw == "EXTRACTED" else "failed"
    return classify_fetch_outcome(
        status=legacy_status,
        failure_code=raw or None,
        http_status=status if isinstance(status, int) else None,
    )


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def extract_main_text(html: str) -> str:
    """Extract a compact main-text representation from an HTML document."""
    if BeautifulSoup is None:
        return _fallback_extract_text(html)

    try:
        soup = BeautifulSoup(html or "", "lxml")
    except Exception:
        soup = BeautifulSoup(html or "", "html.parser")

    # Some publisher pages render their article with JavaScript, but include
    # the complete articleBody in the HTML response. Read it before removing
    # script tags; this does not make another HTTP request.
    structured_text = _structured_article_text(soup)

    candidates = []
    for selector in CONTAINER_SELECTORS:
        candidates.extend(soup.select(selector))

    if candidates:
        best = max(candidates, key=lambda node: len(_clean_text(node.get_text(" "))))
    else:
        best = soup.body or soup

    # Clean only inside the selected document.  In particular, do not remove
    # form/header/footer containers: on several public-sector sites they are
    # ancestors of the main content rather than disposable page chrome.
    for tag in best.select(",".join(REMOVE_SELECTORS)):
        tag.decompose()

    return _clean_text(best.get_text(" ")) or structured_text


def _structured_article_text(soup) -> str:
    texts = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            payload = json.loads(script.string or script.get_text() or "")
        except (TypeError, ValueError):
            continue
        pending = [payload]
        inspected = 0
        while pending and inspected < 100:
            item = pending.pop()
            inspected += 1
            if isinstance(item, list):
                pending.extend(item[:100])
            elif isinstance(item, dict):
                value = item.get("articleBody")
                if isinstance(value, str):
                    cleaned = _clean_text(value)
                    if len(cleaned) >= 120:
                        texts.append(cleaned)
                pending.extend(value for value in item.values() if isinstance(value, (dict, list)))
    return max(texts, key=len, default="")


def _fallback_extract_text(html: str) -> str:
    text = html or ""
    for selector in ("article", "main"):
        match = re.search(rf"<\s*{selector}\b[^>]*>(.*?)<\s*/\s*{selector}\s*>", text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            text = match.group(1)
            break
    for tag in REMOVE_SELECTORS:
        text = re.sub(rf"<\s*{tag}\b[^>]*>.*?<\s*/\s*{tag}\s*>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return _clean_text(text)


def extract_pdf_text(content: bytes) -> str:
    """Extract text from a PDF payload without invoking external binaries."""
    if PdfReader is None:
        raise RuntimeError("pdf_parser_unavailable")

    reader = PdfReader(BytesIO(content))
    return _clean_text(
        " ".join(page.extract_text() or "" for page in islice(reader.pages, PDF_MAX_PAGES))
    )


def detect_document_format(content_type: str, content: bytes) -> str:
    """Detect the payload format from bytes first and headers second."""
    sample = (content or b"")[:1024].lstrip()
    lowered = sample.lower()
    if sample.startswith(b"%PDF-"):
        return "PDF"
    if lowered.startswith((b"<!doctype html", b"<html", b"<head", b"<body")) or b"<html" in lowered:
        return "HTML"
    if content_type in PDF_CONTENT_TYPES:
        return "PDF"
    if content_type in HTML_CONTENT_TYPES:
        return "HTML"
    if content_type in TEXT_CONTENT_TYPES or content_type.startswith("text/"):
        return "TEXT"
    return "UNKNOWN"


def block_page_code(text: str) -> Optional[str]:
    folded = _clean_text(text).casefold()
    if any(marker in folded for marker in BLOCK_PAGE_MARKERS):
        return "BLOCK_PAGE"
    return None


def failure_metadata(error: str, stage: str) -> tuple[str, bool]:
    """Map legacy errors to stable diagnostic codes and retryability."""
    if error.startswith("http_"):
        try:
            status = int(error.split("_", 1)[1])
        except ValueError:
            status = 0
        code = "HTTP_RATE_LIMITED" if status == 429 else (
            "HTTP_SERVER_ERROR" if status >= 500 else "HTTP_CLIENT_ERROR")
        return code, status == 429 or status >= 500
    mapping = {
        "http_timeout": ("TIMEOUT", True),
        "connect_error": ("NETWORK_ERROR", True),
        "tls_hostname_mismatch": ("TLS_HOSTNAME_MISMATCH", True),
        "non_html_content_type": ("FORMAT_UNSUPPORTED", False),
        "pdf_parser_unavailable": ("FORMAT_UNSUPPORTED", False),
        "pdf_text_extraction_failed": ("EXTRACTOR_ERROR", False),
        "pdf_too_large": ("DOCUMENT_TOO_LARGE", False),
        "unsupported_url_scheme": ("UNSUPPORTED_URL", False),
        "empty_body": ("BODY_EMPTY", True),
        "html_no_main_content": ("HTML_NO_MAIN_CONTENT", True),
        "pdf_no_text": ("PDF_NO_TEXT", False),
        "text_empty": ("BODY_EMPTY", True),
        "block_page": ("BLOCK_PAGE", False),
    }
    return mapping.get(error, ("FETCH_ERROR" if stage == "FETCH" else "EXTRACTOR_ERROR", True))


def _fetch_error_code(exc: Exception) -> str:
    """Return a stable, non-sensitive reason suitable for API responses."""
    message = str(exc).lower()
    if (
        "certificate_verify_failed" in message
        and ("hostname mismatch" in message or "not valid for" in message)
    ):
        return "tls_hostname_mismatch"
    if isinstance(exc, httpx.TimeoutException):
        return "http_timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connect_error"
    return exc.__class__.__name__


async def _validate_fetch_url(url: str) -> Optional[str]:
    """Reject malformed or non-public HTTP destinations before connecting."""
    try:
        parsed = urlparse(url)
        port = parsed.port
    except (TypeError, ValueError):
        return "REDIRECT_INVALID_URL"
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443 if parsed.scheme == "https" else 80)
    ):
        return "REDIRECT_UNSAFE_TARGET"
    hostname = parsed.hostname.rstrip(".").lower()
    try:
        addresses = {ipaddress.ip_address(hostname)}
    except ValueError:
        try:
            records = await asyncio.to_thread(
                socket.getaddrinfo, hostname, port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
            addresses = {ipaddress.ip_address(record[4][0]) for record in records}
        except (OSError, ValueError):
            return "REDIRECT_DNS_FAILURE"
    if not addresses or any(not address.is_global for address in addresses):
        return "REDIRECT_UNSAFE_TARGET"
    return None


async def _get_following_validated_redirects(client, url: str, attempted_urls: List[str],
                                              attempts: List[dict]):
    """Fetch a URL while validating every redirect destination before use."""
    current = url
    visited = set()
    redirects = 0
    while True:
        reason = await _validate_fetch_url(current)
        if reason:
            attempts.append({"url": current, "outcome": reason})
            return None, reason
        if current in visited:
            attempts.append({"url": current, "outcome": "REDIRECT_LOOP"})
            return None, "REDIRECT_LOOP"
        visited.add(current)
        response = await client.get(current, follow_redirects=False)
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response, None
        location = response.headers.get("location")
        if not location:
            attempts.append({"url": current, "http_status": response.status_code,
                             "outcome": "REDIRECT_MISSING_LOCATION"})
            return None, "REDIRECT_MISSING_LOCATION"
        if redirects >= MAX_REDIRECTS:
            attempts.append({"url": current, "http_status": response.status_code,
                             "outcome": "REDIRECT_LIMIT_EXCEEDED"})
            return None, "REDIRECT_LIMIT_EXCEEDED"
        target = urljoin(current, location)
        target_reason = await _validate_fetch_url(target)
        if target_reason:
            attempts.append({"url": target, "http_status": response.status_code,
                             "outcome": target_reason})
            return None, target_reason
        if urlparse(current).scheme == "https" and urlparse(target).scheme != "https":
            attempts.append({"url": target, "http_status": response.status_code,
                             "outcome": "REDIRECT_HTTPS_DOWNGRADE"})
            return None, "REDIRECT_HTTPS_DOWNGRADE"
        attempted_urls.append(target)
        attempts.append({"url": current, "http_status": response.status_code,
                         "redirect_to": target, "outcome": "HTTP_REDIRECT"})
        current = target
        redirects += 1


def www_hostname_variant(url: str) -> Optional[str]:
    """Return the only safe hostname alias we may try after a TLS name error.

    This never disables certificate validation and never changes a host beyond
    adding/removing its leading ``www.`` label.  Credentials, non-standard
    ports and IP literals are deliberately excluded.
    """
    parsed = urlparse(url or "")
    try:
        port = parsed.port
    except ValueError:
        return None
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or not hostname
        or "." not in hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        return None
    # Hostname aliases are meaningful only for DNS names, never for an IP.
    if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", hostname) or ":" in hostname:
        return None

    candidate_hostname = hostname[4:] if hostname.startswith("www.") else f"www.{hostname}"
    if not candidate_hostname or "." not in candidate_hostname:
        return None
    netloc = candidate_hostname if port in (None, 443) else f"{candidate_hostname}:{port}"
    return urlunparse(parsed._replace(netloc=netloc))


def parse_retry_after(value: Optional[str], now: Optional[datetime] = None) -> Optional[float]:
    """Parse Retry-After delta seconds or HTTP date without exceeding policy caps."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        target = parsedate_to_datetime(value)
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        return max(0.0, (target - current).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def should_retry_fetch(result: FetchResult) -> bool:
    """Retry only transient transport outcomes, never stable access/extraction failures."""
    if not result.retryable or result.outcome not in RETRYABLE_OUTCOMES:
        return False
    # A pending representation without a server-supplied delay is unlikely to
    # materialize during an immediate second request. Connection and TLS
    # failures likewise need a different candidate, not the same URL again.
    if result.outcome == "PENDING":
        return result.retry_after_seconds is not None
    if result.outcome == "NETWORK_FAILURE":
        return result.failure_code == "TIMEOUT"
    return True


def retry_delay_seconds(result: FetchResult, retry_number: int) -> float:
    """Return a bounded Retry-After/backoff delay with proportional jitter."""
    if result.retry_after_seconds is not None:
        base = result.retry_after_seconds
    else:
        base = min(
            FETCH_RETRY_BASE_SECONDS * (2 ** max(0, retry_number - 1)),
            FETCH_RETRY_MAX_SECONDS,
        )
    if not base or not FETCH_RETRY_JITTER_RATIO:
        return base
    spread = base * FETCH_RETRY_JITTER_RATIO
    return max(0.0, random.uniform(base - spread, base + spread))


def _merge_attempt_urls(target: List[str], source: Optional[List[str]]) -> None:
    for item in source or []:
        if item not in target:
            target.append(item)


async def fetch_main_text(url: str, timeout: float = 10.0,
                          user_agent: str = "TrustNewsEvidenceBot/1.0") -> FetchResult:
    """Fetch with a bounded, outcome-driven retry policy."""
    started = time.monotonic()
    all_attempts: List[dict] = []
    all_urls: List[str] = []
    retry_trace: List[dict] = []
    result: Optional[FetchResult] = None

    for attempt_number in range(1, FETCH_MAX_ATTEMPTS + 1):
        elapsed = time.monotonic() - started
        remaining = FETCH_RETRY_BUDGET_SECONDS - elapsed
        if attempt_number > 1 and remaining <= 0:
            break
        effective_timeout = min(timeout, remaining) if FETCH_RETRY_BUDGET_SECONDS else timeout
        result = await _fetch_main_text_once(
            url,
            timeout=max(0.001, effective_timeout),
            user_agent=user_agent,
        )
        for attempt in result.attempts or []:
            all_attempts.append({**attempt, "attempt_number": attempt_number})
        _merge_attempt_urls(all_urls, result.attempted_urls)

        if attempt_number >= FETCH_MAX_ATTEMPTS or not should_retry_fetch(result):
            break
        delay = retry_delay_seconds(result, attempt_number)
        elapsed = time.monotonic() - started
        if delay > FETCH_RETRY_MAX_SECONDS or (
            FETCH_RETRY_BUDGET_SECONDS and elapsed + delay >= FETCH_RETRY_BUDGET_SECONDS
        ):
            retry_trace.append({
                "after_attempt": attempt_number,
                "outcome": result.outcome,
                "action": "RETRY_SKIPPED_BUDGET",
                "delay_seconds": round(delay, 3),
                "reason": "RETRY_AFTER_TOO_LONG" if delay > FETCH_RETRY_MAX_SECONDS else "TIME_BUDGET",
            })
            break
        retry_trace.append({
            "after_attempt": attempt_number,
            "outcome": result.outcome,
            "action": "RETRY",
            "delay_seconds": round(delay, 3),
            "retry_after_observed": result.retry_after_seconds is not None,
        })
        if delay:
            await asyncio.sleep(delay)

    if result is None:  # Defensive: FETCH_MAX_ATTEMPTS is clamped to at least one.
        return FetchResult(status="failed", error="retry_budget_exhausted",
                           failure_stage="FETCH", failure_code="TIMEOUT", retryable=True)
    result.attempts = all_attempts
    result.attempted_urls = all_urls or [url]
    result.retry_trace = retry_trace
    return result


async def _fetch_main_text_once(url: str, timeout: float = 10.0,
                                user_agent: str = "TrustNewsEvidenceBot/1.0") -> FetchResult:
    """Download and extract a document while retaining structured diagnostics."""
    parsed = urlparse(url or "")
    if parsed.scheme not in {"http", "https"}:
        code, retryable = failure_metadata("unsupported_url_scheme", "FETCH")
        return FetchResult(status="failed", error="unsupported_url_scheme", attempted_urls=[url],
                           failure_stage="FETCH", failure_code=code, retryable=retryable,
                           attempts=[{"url": url, "outcome": code}])

    attempted_urls = [url]
    attempts = []
    normalized_url = None
    normalization_reason = None
    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=timeout,
            headers={"User-Agent": user_agent},
        ) as client:
            try:
                response, redirect_error = await _get_following_validated_redirects(
                    client, url, attempted_urls, attempts,
                )
                if redirect_error:
                    return FetchResult(
                        status="failed", error=redirect_error, attempted_urls=attempted_urls,
                        failure_stage="FETCH", failure_code=redirect_error, retryable=False,
                        attempts=attempts,
                    )
            except Exception as exc:
                error = _fetch_error_code(exc)
                code, retryable = failure_metadata(error, "FETCH")
                attempts.append({"url": url, "outcome": code})
                normalized_url = www_hostname_variant(url) if error == "tls_hostname_mismatch" else None
                if not normalized_url:
                    return FetchResult(status="failed", error=error, attempted_urls=attempted_urls,
                                       failure_stage="FETCH", failure_code=code, retryable=retryable,
                                       attempts=attempts)
                attempted_urls.append(normalized_url)
                normalization_reason = "tls_hostname_mismatch_www_variant"
                try:
                    # The retry still uses httpx's default certificate checks.
                    response, redirect_error = await _get_following_validated_redirects(
                        client, normalized_url, attempted_urls, attempts,
                    )
                    if redirect_error:
                        return FetchResult(
                            status="failed", error=redirect_error,
                            normalization_reason=normalization_reason,
                            attempted_urls=attempted_urls, failure_stage="FETCH",
                            failure_code=redirect_error, retryable=False, attempts=attempts,
                        )
                except Exception as retry_exc:
                    retry_error = _fetch_error_code(retry_exc)
                    retry_code, retryable = failure_metadata(retry_error, "FETCH")
                    attempts.append({"url": normalized_url, "outcome": retry_code})
                    return FetchResult(
                        status="failed",
                        error=retry_error,
                        normalization_reason=normalization_reason,
                        attempted_urls=attempted_urls,
                        failure_stage="FETCH",
                        failure_code=retry_code,
                        retryable=retryable,
                        attempts=attempts,
                    )
    except Exception as exc:
        error = _fetch_error_code(exc)
        code, retryable = failure_metadata(error, "FETCH")
        attempts.append({"url": attempted_urls[-1], "outcome": code})
        return FetchResult(status="failed", error=error, attempted_urls=attempted_urls,
                           failure_stage="FETCH", failure_code=code, retryable=retryable,
                           attempts=attempts)

    content_type = (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    fetched_url = str(getattr(response, "url", url))
    http_status = int(response.status_code)
    response_bytes = len(response.content or b"")
    retry_after_seconds = parse_retry_after(response.headers.get("retry-after"))
    url_normalized = bool(normalized_url) or fetched_url != url
    if not normalization_reason and fetched_url != url:
        normalization_reason = "http_redirect"
    if response.status_code >= 400:
        error = f"http_{response.status_code}"
        code, retryable = failure_metadata(error, "FETCH")
        attempts.append({"url": fetched_url, "http_status": http_status, "outcome": code})
        return FetchResult(status="failed", error=error, content_type=content_type,
                           fetched_url=fetched_url, url_normalized=url_normalized,
                           normalization_reason=normalization_reason, attempted_urls=attempted_urls,
                           failure_stage="FETCH", failure_code=code, retryable=retryable,
                           http_status=http_status, response_bytes=response_bytes, attempts=attempts,
                           retry_after_seconds=retry_after_seconds)

    if http_status == 202 and response_bytes == 0:
        # A successful-looking 202 with no representation cannot be parsed.
        # Keep it as an unusable source, but expose a precise reason so URL
        # selection can replace it with another candidate from the same batch.
        attempts.append({"url": fetched_url, "http_status": http_status, "response_bytes": 0,
                         "declared_content_type": content_type,
                         "outcome": "HTTP_202_EMPTY_BODY"})
        return FetchResult(
            status="empty_text", content_type=content_type, fetched_url=fetched_url,
            url_normalized=url_normalized, normalization_reason=normalization_reason,
            attempted_urls=attempted_urls, failure_stage="FETCH",
            failure_code="HTTP_202_EMPTY_BODY", retryable=True,
            http_status=http_status, response_bytes=0,
            detected_format="HTML" if content_type in HTML_CONTENT_TYPES else None,
            extractor="html" if content_type in HTML_CONTENT_TYPES else None,
            retry_after_seconds=retry_after_seconds,
            attempts=attempts,
        )

    detected_format = detect_document_format(content_type, response.content)
    extractor = detected_format.lower() if detected_format != "UNKNOWN" else None
    attempts.append({"url": fetched_url, "http_status": http_status, "response_bytes": response_bytes,
                     "declared_content_type": content_type, "detected_format": detected_format,
                     "outcome": "FETCH_OK"})
    extraction_error = None
    if detected_format == "PDF":
        if len(response.content) > PDF_MAX_BYTES:
            extraction_error, text = "pdf_too_large", ""
        else:
            try:
                # PDF parsing is CPU-bound. Keep it off the ASGI event loop so
                # health probes and concurrent searches remain responsive.
                text = await asyncio.to_thread(extract_pdf_text, response.content)
            except RuntimeError as exc:
                extraction_error, text = str(exc), ""
            except Exception:
                extraction_error, text = "pdf_text_extraction_failed", ""
            if not extraction_error and not text:
                extraction_error = "pdf_no_text"
    elif detected_format == "HTML":
        # BeautifulSoup/lxml parsing is synchronous as well and can be costly
        # for large public-sector pages.
        text = await asyncio.to_thread(extract_main_text, response.text)
        if not text:
            extraction_error = "empty_body" if not response.content else "html_no_main_content"
        elif block_page_code(text):
            extraction_error, text = "block_page", ""
    elif detected_format == "TEXT":
        encoding = getattr(response, "encoding", None) or "utf-8"
        try:
            decoded = response.content.decode(encoding, errors="replace")
        except LookupError:
            decoded = response.content.decode("utf-8", errors="replace")
        text = _clean_text(decoded)
        if not text:
            extraction_error = "text_empty"
    else:
        extraction_error, text = "non_html_content_type", ""

    if extraction_error:
        code, retryable = failure_metadata(extraction_error, "EXTRACTION")
        attempts[-1]["outcome"] = code
        legacy_status = "empty_text" if code in {
            "BODY_EMPTY", "HTML_NO_MAIN_CONTENT", "PDF_NO_TEXT", "BLOCK_PAGE"
        } else "failed"
        return FetchResult(status=legacy_status,
                           error=None if legacy_status == "empty_text" else extraction_error,
                           content_type=content_type, fetched_url=fetched_url,
                           url_normalized=url_normalized, normalization_reason=normalization_reason,
                           attempted_urls=attempted_urls, failure_stage="EXTRACTION",
                           failure_code=code, retryable=retryable, http_status=http_status,
                           response_bytes=response_bytes, detected_format=detected_format,
                           extractor=extractor, attempts=attempts)

    attempts[-1]["outcome"] = "EXTRACTED"
    return FetchResult(status="ok", text=text, content_type=content_type, fetched_url=fetched_url,
                       url_normalized=url_normalized, normalization_reason=normalization_reason,
                       attempted_urls=attempted_urls, http_status=http_status,
                       response_bytes=response_bytes, detected_format=detected_format,
                       extractor=extractor, attempts=attempts)
