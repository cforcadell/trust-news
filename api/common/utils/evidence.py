import re
import unicodedata
from typing import Any, Dict, Iterable
from urllib.parse import urlparse, urlunparse

from pydantic import BeforeValidator, HttpUrl, TypeAdapter, ValidationError
from typing_extensions import Annotated


_http_url = TypeAdapter(HttpUrl)


def is_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    value = value.strip()
    # Reject characters that URL parsers may silently remove or reinterpret.
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 or char == "\\" for char in value):
        return False
    try:
        parsed = urlparse(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return False
        _http_url.validate_python(value)
    except (ValueError, ValidationError):
        return False
    return True


def sanitize_evidence_item(value: Any) -> Any:
    if not isinstance(value, dict):
        return value

    item = dict(value)
    for key in ("url", "source_url"):
        if key in item and item[key] not in (None, "") and not is_http_url(item[key]):
            # Preserve the original for display without making it navigable.
            if isinstance(item[key], str):
                item[f"{key}_text"] = item[key]
            item.pop(key)
    return item


EvidenceItem = Annotated[Dict[str, Any], BeforeValidator(sanitize_evidence_item)]

_ROUTING_PLACEHOLDER_TEXT = (
    "domain selected by contextual routing; configure api_key_provider for live snippets."
)


def _canonical_http_url(value: Any) -> str | None:
    """Return a comparison-safe HTTP(S) URL without its fragment."""
    if not is_http_url(value):
        return None
    parsed = urlparse(str(value).strip())
    host = (parsed.hostname or "").lower()
    port = parsed.port
    default_port = (parsed.scheme.lower() == "http" and port == 80) or (
        parsed.scheme.lower() == "https" and port == 443
    )
    netloc = host if port is None or default_port else f"{host}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunparse((parsed.scheme.lower(), netloc, path, "", parsed.query, ""))


def _normalized_evidence_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip().casefold()


def _is_placeholder_evidence(source: Dict[str, Any]) -> bool:
    if source.get("is_placeholder") or source.get("evidence_status") == "ROUTING_PLACEHOLDER":
        return True
    # Cached responses created before evidence_status was added must remain
    # non-evidentiary as well.
    candidate = source.get("snippet") or source.get("content") or ""
    return _normalized_evidence_text(candidate) == _ROUTING_PLACEHOLDER_TEXT


def _source_texts(source: Dict[str, Any], reference: Dict[str, Any]) -> Iterable[str]:
    contexts = source.get("contexts") or source.get("chunks") or []
    context_id = str(reference.get("context_id") or "").strip()
    chunk_id = str(reference.get("chunk_id") or "").strip()

    for context in contexts:
        if not isinstance(context, dict):
            continue
        if context_id and str(context.get("context_id") or "") != context_id:
            continue
        if chunk_id:
            possible_chunk_ids = {
                str(context.get("chunk_id") or ""),
                str(context.get("selected_chunk_id") or ""),
                *(str(value) for value in context.get("included_chunk_ids") or []),
            }
            if chunk_id not in possible_chunk_ids:
                continue
        yield str(context.get("text") or "")

    # Legacy/provider responses may only expose a bounded search snippet.
    if not context_id and not chunk_id:
        for key in ("snippet", "excerpt", "content"):
            if source.get(key):
                yield str(source[key])


def evaluate_evidence_grounding(
    verdict: Any,
    evidence_used: Any,
    retrieved_evidence: Any,
    *,
    require_grounding: bool,
    non_documentary_basis: str = "MODEL_KNOWLEDGE",
) -> Dict[str, Any]:
    """Validate citations against evidence actually retrieved by the server.

    The function deliberately does not infer that every retrieved source was used.
    Unsupported documentary TRUE/FALSE results are converted to UNKNOWN, while
    malformed or invented citations are removed from the public evidence list.
    """
    original_verdict = str(getattr(verdict, "name", verdict) or "UNKNOWN").upper()
    if original_verdict not in {"TRUE", "FALSE", "UNKNOWN"}:
        original_verdict = "UNKNOWN"

    claimed = evidence_used if isinstance(evidence_used, list) else []
    retrieved = retrieved_evidence if isinstance(retrieved_evidence, list) else []
    retrieved_by_id = {
        str(item.get("source_id")): item
        for item in retrieved
        if isinstance(item, dict) and item.get("source_id")
    }
    verified: list[Dict[str, Any]] = []
    issues: list[Dict[str, Any]] = []

    for index, raw_reference in enumerate(claimed):
        if not isinstance(raw_reference, dict):
            issues.append({"index": index, "code": "INVALID_EVIDENCE_ITEM"})
            continue
        reference = sanitize_evidence_item(raw_reference)
        source_id = str(reference.get("source_id") or "").strip()
        source = retrieved_by_id.get(source_id)
        if source is None:
            issues.append({"index": index, "code": "SOURCE_NOT_RETRIEVED", "source_id": source_id or None})
            continue
        if _is_placeholder_evidence(source):
            issues.append({"index": index, "code": "SOURCE_IS_PLACEHOLDER", "source_id": source_id})
            continue

        reference_url = _canonical_http_url(reference.get("url"))
        source_url = _canonical_http_url(source.get("url"))
        if reference_url is None:
            issues.append({"index": index, "code": "URL_REQUIRED", "source_id": source_id})
            continue
        if source_url is None or reference_url != source_url:
            issues.append({"index": index, "code": "URL_NOT_RETRIEVED", "source_id": source_id})
            continue

        quote = reference.get("evidence_text") or reference.get("quote")
        normalized_quote = _normalized_evidence_text(quote)
        if not normalized_quote:
            issues.append({"index": index, "code": "EVIDENCE_TEXT_REQUIRED", "source_id": source_id})
            continue
        candidate_texts = [_normalized_evidence_text(text) for text in _source_texts(source, reference)]
        if not any(normalized_quote in text for text in candidate_texts if text):
            issues.append({"index": index, "code": "EVIDENCE_TEXT_NOT_RETRIEVED", "source_id": source_id})
            continue
        verified.append(reference)

    expected_support = True if original_verdict == "TRUE" else False
    supports_verdict = any(item.get("supports") is expected_support for item in verified)
    decisive = original_verdict in {"TRUE", "FALSE"}
    effective_verdict = original_verdict

    if not require_grounding:
        # Memory and provider-managed search are not documentary evidence. Do
        # not publish citations as evidence_used when the server has no corpus
        # against which to check them.
        provider_search = non_documentary_basis == "PROVIDER_SEARCH_UNVERIFIED"
        return {
            "effective_verdict": effective_verdict,
            "evidence_used": [],
            "validation": {
                "status": "UNVERIFIED" if provider_search else "NOT_APPLICABLE",
                "basis": non_documentary_basis,
                "original_verdict": original_verdict,
                "effective_verdict": effective_verdict,
                "claimed_count": len(claimed),
                "verified_count": 0,
                "rejected_count": 0 if provider_search else len(claimed),
                "issues": (
                    [{"code": "PROVIDER_SOURCES_NOT_SERVER_VERIFIED"}]
                    if provider_search and claimed
                    else ([{"code": "DOCUMENTARY_EVIDENCE_NOT_AVAILABLE"}] if claimed else [])
                ),
            },
        }

    if decisive and not supports_verdict:
        effective_verdict = "UNKNOWN"
        status = "UNSUPPORTED"
        issues.append({"code": "VERDICT_WITHOUT_SUPPORT", "verdict": original_verdict})
    elif issues:
        status = "PARTIALLY_VERIFIED" if verified else "INVALID"
    elif verified:
        status = "VERIFIED"
    else:
        status = "NOT_REQUIRED" if original_verdict == "UNKNOWN" else "UNSUPPORTED"

    return {
        "effective_verdict": effective_verdict,
        "evidence_used": verified,
        "validation": {
            "status": status,
            "basis": "RETRIEVED_EVIDENCE",
            "original_verdict": original_verdict,
            "effective_verdict": effective_verdict,
            "claimed_count": len(claimed),
            "verified_count": len(verified),
            "rejected_count": len(claimed) - len(verified),
            "issues": issues,
        },
    }
