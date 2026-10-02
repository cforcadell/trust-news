import re
from io import BytesIO
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

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


async def fetch_main_text(url: str, timeout: float = 10.0, user_agent: str = "TrustNewsEvidenceBot/1.0") -> FetchResult:
    """Download HTML or PDF and return extracted text without raising endpoint-level errors."""
    parsed = urlparse(url or "")
    if parsed.scheme not in {"http", "https"}:
        return FetchResult(status="failed", error="unsupported_url_scheme")

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": user_agent},
        ) as client:
            response = await client.get(url)
    except Exception as exc:
        return FetchResult(status="failed", error=exc.__class__.__name__)

    content_type = (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if response.status_code >= 400:
        return FetchResult(status="failed", error=f"http_{response.status_code}", content_type=content_type)
    if content_type in PDF_CONTENT_TYPES:
        if len(response.content) > PDF_MAX_BYTES:
            return FetchResult(status="failed", error="pdf_too_large", content_type=content_type)
        try:
            text = extract_pdf_text(response.content)
        except RuntimeError as exc:
            return FetchResult(status="failed", error=str(exc), content_type=content_type)
        except Exception:
            return FetchResult(status="failed", error="pdf_text_extraction_failed", content_type=content_type)
    elif content_type in HTML_CONTENT_TYPES:
        text = extract_main_text(response.text)
    else:
        return FetchResult(status="failed", error="non_html_content_type", content_type=content_type)
    if not text:
        return FetchResult(status="empty_text", content_type=content_type)
    return FetchResult(status="ok", text=text, content_type=content_type)
