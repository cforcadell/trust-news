import re
from io import BytesIO
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlparse, urlunparse

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
REMOVE_SELECTORS = ("script", "style", "noscript", "svg", "form", "nav", "footer", "header")
PDF_MAX_BYTES = 15 * 1024 * 1024
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

    @property
    def document_length_chars(self) -> int:
        return len(self.text)


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

    for tag in soup.select(",".join(REMOVE_SELECTORS)):
        tag.decompose()

    candidates = []
    for selector in ("article", "main", '[role="main"]'):
        candidates.extend(soup.select(selector))

    if candidates:
        best = max(candidates, key=lambda node: len(_clean_text(node.get_text(" "))))
    else:
        best = soup.body or soup

    return _clean_text(best.get_text(" "))


def _fallback_extract_text(html: str) -> str:
    text = html or ""
    for tag in REMOVE_SELECTORS:
        text = re.sub(rf"<\s*{tag}\b[^>]*>.*?<\s*/\s*{tag}\s*>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    for selector in ("article", "main"):
        match = re.search(rf"<\s*{selector}\b[^>]*>(.*?)<\s*/\s*{selector}\s*>", text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            text = match.group(1)
            break
    text = re.sub(r"<[^>]+>", " ", text)
    return _clean_text(text)


def extract_pdf_text(content: bytes) -> str:
    """Extract text from a PDF payload without invoking external binaries."""
    if PdfReader is None:
        raise RuntimeError("pdf_parser_unavailable")

    reader = PdfReader(BytesIO(content))
    return _clean_text(" ".join(page.extract_text() or "" for page in reader.pages))


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
        "block_page": ("BLOCK_PAGE", True),
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


async def fetch_main_text(url: str, timeout: float = 10.0, user_agent: str = "TrustNewsEvidenceBot/1.0") -> FetchResult:
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
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": user_agent},
        ) as client:
            try:
                response = await client.get(url)
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
                    response = await client.get(normalized_url)
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
                           http_status=http_status, response_bytes=response_bytes, attempts=attempts)

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
                text = extract_pdf_text(response.content)
            except RuntimeError as exc:
                extraction_error, text = str(exc), ""
            except Exception:
                extraction_error, text = "pdf_text_extraction_failed", ""
            if not extraction_error and not text:
                extraction_error = "pdf_no_text"
    elif detected_format == "HTML":
        text = extract_main_text(response.text)
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
