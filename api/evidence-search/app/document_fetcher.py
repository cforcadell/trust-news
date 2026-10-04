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
REMOVE_SELECTORS = ("script", "style", "noscript", "svg", "form", "nav", "footer", "header")
PDF_MAX_BYTES = 15 * 1024 * 1024


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
    """Download HTML or PDF and return extracted text without raising endpoint-level errors."""
    parsed = urlparse(url or "")
    if parsed.scheme not in {"http", "https"}:
        return FetchResult(status="failed", error="unsupported_url_scheme", attempted_urls=[url])

    attempted_urls = [url]
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
                normalized_url = www_hostname_variant(url) if error == "tls_hostname_mismatch" else None
                if not normalized_url:
                    return FetchResult(status="failed", error=error, attempted_urls=attempted_urls)
                attempted_urls.append(normalized_url)
                normalization_reason = "tls_hostname_mismatch_www_variant"
                try:
                    # The retry still uses httpx's default certificate checks.
                    response = await client.get(normalized_url)
                except Exception:
                    return FetchResult(
                        status="failed",
                        error=error,
                        normalization_reason=normalization_reason,
                        attempted_urls=attempted_urls,
                    )
    except Exception as exc:
        return FetchResult(status="failed", error=_fetch_error_code(exc), attempted_urls=attempted_urls)

    content_type = (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    fetched_url = str(getattr(response, "url", url))
    url_normalized = bool(normalized_url) or fetched_url != url
    if not normalization_reason and fetched_url != url:
        normalization_reason = "http_redirect"
    if response.status_code >= 400:
        return FetchResult(status="failed", error=f"http_{response.status_code}", content_type=content_type,
                           fetched_url=fetched_url, url_normalized=url_normalized,
                           normalization_reason=normalization_reason, attempted_urls=attempted_urls)
    if content_type in PDF_CONTENT_TYPES:
        if len(response.content) > PDF_MAX_BYTES:
            return FetchResult(status="failed", error="pdf_too_large", content_type=content_type,
                               fetched_url=fetched_url, url_normalized=url_normalized,
                               normalization_reason=normalization_reason, attempted_urls=attempted_urls)
        try:
            text = extract_pdf_text(response.content)
        except RuntimeError as exc:
            return FetchResult(status="failed", error=str(exc), content_type=content_type,
                               fetched_url=fetched_url, url_normalized=url_normalized,
                               normalization_reason=normalization_reason, attempted_urls=attempted_urls)
        except Exception:
            return FetchResult(status="failed", error="pdf_text_extraction_failed", content_type=content_type,
                               fetched_url=fetched_url, url_normalized=url_normalized,
                               normalization_reason=normalization_reason, attempted_urls=attempted_urls)
    elif content_type in HTML_CONTENT_TYPES:
        text = extract_main_text(response.text)
    else:
        return FetchResult(status="failed", error="non_html_content_type", content_type=content_type,
                           fetched_url=fetched_url, url_normalized=url_normalized,
                           normalization_reason=normalization_reason, attempted_urls=attempted_urls)
    if not text:
        return FetchResult(status="empty_text", content_type=content_type, fetched_url=fetched_url,
                           url_normalized=url_normalized, normalization_reason=normalization_reason,
                           attempted_urls=attempted_urls)
    return FetchResult(status="ok", text=text, content_type=content_type, fetched_url=fetched_url,
                       url_normalized=url_normalized, normalization_reason=normalization_reason,
                       attempted_urls=attempted_urls)
