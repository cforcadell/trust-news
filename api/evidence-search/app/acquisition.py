"""Provider-neutral acquisition of the document behind a search result."""

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from common.utils.evidence import is_http_url
from common.search.models import ExtractResult

from .document_fetcher import FetchResult, _validate_fetch_url, block_page_code


@dataclass(frozen=True)
class ExtractionPolicy:
    mode: str = "DIRECT"
    min_document_chars: int = 120
    require_known_freshness: bool = False
    allow_provider_extract: bool = False
    max_content_age_seconds: int = 0
    max_document_chars: int = 1_000_000

    def __post_init__(self) -> None:
        if self.mode not in {"DIRECT", "PROVIDER", "SMART"}:
            raise ValueError("EVIDENCE_EXTRACTION_MODE must be DIRECT, PROVIDER or SMART")
        if self.min_document_chars < 1:
            raise ValueError("EVIDENCE_MIN_DOCUMENT_CHARS must be positive")
        if self.max_content_age_seconds < 0:
            raise ValueError("max_content_age_seconds must not be negative")
        if self.max_document_chars < 1:
            raise ValueError("max_document_chars must be positive")


@dataclass
class AcquisitionResult:
    fetch: FetchResult
    method: str | None
    attempts: list[dict[str, Any]]
    received_at: str | None = None
    freshness_status: str = "UNKNOWN"
    direct_fetch: FetchResult | None = None
    provider: str | None = None
    provider_request_id: str | None = None
    provider_cost_usd: float | None = None
    provider_usage: dict[str, Any] | None = None
    snapshot_id: str | None = None
    cache_origin_method: str | None = None
    source_fetched_at: str | None = None

    @property
    def document_sha256(self) -> str | None:
        if self.fetch.status != "ok" or not self.fetch.text:
            return None
        return hashlib.sha256(self.fetch.text.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _provider_document(source: dict[str, Any], policy: ExtractionPolicy) -> tuple[str, str]:
    """Only raw_content is a document; content/highlights are search excerpts."""
    if not is_http_url(source.get("url")):
        return "", "INVALID_SOURCE_URL"
    raw = source.get("raw_content")
    if not isinstance(raw, str):
        return "", "NO_FULL_TEXT"
    if len(raw) > policy.max_document_chars:
        return "", "DOCUMENT_TOO_LARGE"
    text = re.sub(r"\s+", " ", raw).strip()
    if len(text) < policy.min_document_chars:
        return "", "TEXT_TOO_SHORT"
    if len(text) > policy.max_document_chars:
        return "", "DOCUMENT_TOO_LARGE"
    if block_page_code(text):
        return "", "BLOCK_PAGE"
    if policy.require_known_freshness:
        # Search adapters do not currently provide a trustworthy crawl time.
        return "", "FRESHNESS_UNKNOWN"
    return text, "ACCEPTED"


async def acquire_document(
    source: dict[str, Any],
    url: str,
    policy: ExtractionPolicy,
    fetch_direct: Callable[..., Awaitable[FetchResult]],
    *,
    timeout: float,
    user_agent: str,
    extract_provider: Callable[..., Awaitable[ExtractResult]] | None = None,
    provider: str | None = None,
    extract_budget: list[int] | None = None,
    load_cached: Callable[..., Awaitable[dict[str, Any] | None]] | None = None,
) -> AcquisitionResult:
    """Choose a text acquisition method without changing downstream ranking."""
    attempts: list[dict[str, Any]] = []
    if policy.mode in {"PROVIDER", "SMART"}:
        text, decision = _provider_document(source, policy)
        attempts.append({"method": "provider_search_text", "outcome": decision})
        if text:
            return AcquisitionResult(
                fetch=FetchResult(status="ok", text=text, content_type="text/plain",
                                  fetched_url=url, detected_format="TEXT",
                                  extractor="provider_search_text", attempted_urls=[]),
                method="provider_search_text", attempts=attempts,
                received_at=_utc_now(), freshness_status="UNKNOWN",
            )
        if policy.mode == "PROVIDER" and not policy.allow_provider_extract:
            return AcquisitionResult(
                fetch=FetchResult(status="failed", error=decision,
                                  failure_stage="ACQUISITION", failure_code=decision),
                method=None, attempts=attempts,
            )

    if policy.max_content_age_seconds and load_cached:
        snapshot = await load_cached(url=url, provider=provider,
                                     max_age_seconds=policy.max_content_age_seconds,
                                     require_known_freshness=policy.require_known_freshness)
        if snapshot:
            cached_text = snapshot.get("text") or ""
            if (policy.min_document_chars <= len(cached_text) <= policy.max_document_chars
                    and not block_page_code(cached_text)):
                attempts.append({"method": "document_cache", "outcome": "ACCEPTED",
                                 "snapshot_id": snapshot.get("_id")})
                return AcquisitionResult(
                    fetch=FetchResult(status="ok", text=cached_text, content_type="text/plain",
                                      fetched_url=snapshot.get("resolved_url") or url,
                                      detected_format="TEXT", extractor="document_cache", attempted_urls=[]),
                    method="document_cache", attempts=attempts, received_at=_utc_now(),
                    freshness_status="CACHED_KNOWN_AGE", provider=snapshot.get("provider"),
                    snapshot_id=snapshot.get("_id"), cache_origin_method=snapshot.get("method"),
                    source_fetched_at=snapshot.get("received_at")
                    if snapshot.get("freshness_status") == "OBSERVED_NOW" else None,
                )

    fetched: FetchResult | None = None
    if policy.mode != "PROVIDER":
        fetched = await fetch_direct(url, timeout=timeout, user_agent=user_agent)
        if fetched.status == "ok" and len(fetched.text) > policy.max_document_chars:
            fetched = FetchResult(
                status="failed", error="document_too_large", content_type=fetched.content_type,
                fetched_url=fetched.fetched_url, attempted_urls=fetched.attempted_urls,
                failure_stage="EXTRACTION", failure_code="DOCUMENT_TOO_LARGE", retryable=False,
                http_status=fetched.http_status, response_bytes=fetched.response_bytes,
                detected_format=fetched.detected_format, extractor=fetched.extractor,
                attempts=fetched.attempts, retry_trace=fetched.retry_trace,
            )
        attempts.append({"method": "direct_fetch", "outcome": "ACCEPTED" if fetched.status == "ok" else
                         str(getattr(fetched, "failure_code", None) or fetched.status).upper()})
        if fetched.status == "ok":
            return AcquisitionResult(fetch=fetched, method="direct_fetch", attempts=attempts,
                                     received_at=_utc_now(), freshness_status="OBSERVED_NOW", direct_fetch=fetched)

    if policy.mode in {"SMART", "PROVIDER"} and policy.allow_provider_extract and extract_provider:
        if extract_budget is not None and extract_budget[0] <= 0:
            attempts.append({"method": "provider_extract", "outcome": "BUDGET_EXHAUSTED"})
        else:
            # The provider sees the URL too; never submit private/unsafe targets.
            reason = await _validate_fetch_url(url) if is_http_url(url) else "INVALID_SOURCE_URL"
            if reason:
                attempts.append({"method": "provider_extract", "outcome": reason})
            else:
                if extract_budget is not None:
                    extract_budget[0] -= 1
                start = time.monotonic()
                try:
                    extracted = await extract_provider(provider, url, require_live=policy.require_known_freshness)
                except Exception as exc:
                    attempts.append({"method": "provider_extract", "outcome": "PROVIDER_ERROR",
                                     "duration_ms": round((time.monotonic() - start) * 1000, 2),
                                     "provider": provider,
                                     "error": str(exc)[:200]})
                else:
                    decision = "ACCEPTED" if extracted.status == "ok" else (extracted.error or extracted.status).upper()
                    raw_text = extracted.text or ""
                    if decision == "ACCEPTED" and len(raw_text) > policy.max_document_chars:
                        decision = "DOCUMENT_TOO_LARGE"
                    text = re.sub(r"\s+", " ", raw_text).strip() if decision == "ACCEPTED" else ""
                    if decision == "ACCEPTED" and len(text) < policy.min_document_chars:
                        decision = "TEXT_TOO_SHORT"
                    if decision == "ACCEPTED" and len(text) > policy.max_document_chars:
                        decision = "DOCUMENT_TOO_LARGE"
                    if decision == "ACCEPTED" and block_page_code(text):
                        decision = "BLOCK_PAGE"
                    if decision == "ACCEPTED" and policy.require_known_freshness and extracted.freshness_status != "OBSERVED_NOW":
                        decision = "FRESHNESS_UNPROVEN"
                    attempts.append({"method": "provider_extract", "outcome": decision,
                                     "duration_ms": round((time.monotonic() - start) * 1000, 2),
                                     "provider": provider, "request_id": extracted.request_id,
                                     "cost_usd": extracted.cost_usd, "usage": extracted.usage})
                    if decision == "ACCEPTED":
                        return AcquisitionResult(
                            fetch=FetchResult(status="ok", text=text, content_type="text/plain",
                                              fetched_url=extracted.resolved_url or url, detected_format="TEXT",
                                              extractor="provider_extract", attempted_urls=[]),
                            method="provider_extract", attempts=attempts,
                            received_at=_utc_now(), freshness_status=extracted.freshness_status,
                            direct_fetch=fetched, provider=provider,
                            provider_request_id=extracted.request_id,
                            provider_cost_usd=extracted.cost_usd, provider_usage=extracted.usage,
                        )
    if fetched is None:
        fetched = FetchResult(status="failed", error="PROVIDER_EXTRACTION_FAILED",
                              failure_stage="ACQUISITION", failure_code="PROVIDER_EXTRACTION_FAILED")
    return AcquisitionResult(
        fetch=fetched, method=None, attempts=attempts, direct_fetch=fetched if policy.mode != "PROVIDER" else None,
    )
