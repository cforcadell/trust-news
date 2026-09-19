from typing import Any, Dict
from urllib.parse import urlparse

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

def _citation_contexts(
    retrieved_evidence: Any,
) -> tuple[Dict[str, tuple[Dict[str, Any], Dict[str, Any]]], set[str], set[str]]:
    """Index server-created citation contexts and report ambiguous identifiers."""
    indexed: Dict[str, tuple[Dict[str, Any], Dict[str, Any]]] = {}
    ambiguous: set[str] = set()
    uncitable: set[str] = set()
    for source in retrieved_evidence if isinstance(retrieved_evidence, list) else []:
        if not isinstance(source, dict):
            continue
        for context in source.get("contexts") or []:
            if not isinstance(context, dict):
                continue
            context_id = str(context.get("context_id") or "").strip()
            if not context_id:
                continue
            if context.get("citation_eligible") is not True or not str(context.get("text") or "").strip():
                uncitable.add(context_id)
                continue
            if context_id in indexed:
                ambiguous.add(context_id)
                indexed.pop(context_id, None)
                continue
            if context_id not in ambiguous:
                indexed[context_id] = (source, context)
    return indexed, ambiguous, uncitable


def _canonical_evidence_reference(
    source: Dict[str, Any],
    context: Dict[str, Any],
    claimed: Dict[str, Any],
) -> Dict[str, Any]:
    """Build public evidence exclusively from server-retrieved canonical data."""
    reference = {
        "source_id": source.get("source_id"),
        "context_id": context.get("context_id"),
        "url": source.get("url"),
        "title": source.get("title"),
        "supports": claimed.get("supports"),
        "evidence_text": context.get("text"),
        "reason": str(claimed.get("reason") or "").strip(),
    }
    selected_chunk_id = context.get("selected_chunk_id")
    if selected_chunk_id:
        reference["chunk_id"] = selected_chunk_id
    text_sha256 = context.get("text_sha256")
    if text_sha256:
        reference["evidence_text_sha256"] = text_sha256
    return sanitize_evidence_item(reference)


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
    citation_contexts, ambiguous_contexts, uncitable_contexts = _citation_contexts(retrieved)
    verified: list[Dict[str, Any]] = []
    issues: list[Dict[str, Any]] = []

    for index, raw_reference in enumerate(claimed):
        if not isinstance(raw_reference, dict):
            issues.append({"index": index, "code": "INVALID_EVIDENCE_ITEM"})
            continue
        context_id = str(raw_reference.get("context_id") or "").strip()
        if not context_id:
            issues.append({"index": index, "code": "CONTEXT_ID_REQUIRED"})
            continue
        if context_id in ambiguous_contexts:
            issues.append({"index": index, "code": "CONTEXT_ID_AMBIGUOUS", "context_id": context_id})
            continue
        if context_id in uncitable_contexts:
            issues.append({"index": index, "code": "CONTEXT_NOT_CITABLE", "context_id": context_id})
            continue
        resolved = citation_contexts.get(context_id)
        if resolved is None:
            issues.append({"index": index, "code": "CONTEXT_NOT_RETRIEVED", "context_id": context_id})
            continue
        source, context = resolved
        source_id = str(source.get("source_id") or "").strip()
        if source.get("relationship_to_origin") == "ORIGINAL":
            issues.append({
                "index": index,
                "code": "SOURCE_IS_ORIGINAL_DOCUMENT",
                "source_id": source_id,
                "context_id": context_id,
            })
            continue
        if not is_http_url(source.get("url")):
            issues.append({"index": index, "code": "RETRIEVED_SOURCE_URL_INVALID", "source_id": source_id})
            continue
        if not isinstance(raw_reference.get("supports"), bool):
            issues.append({"index": index, "code": "SUPPORTS_REQUIRED", "context_id": context_id})
            continue
        verified.append(_canonical_evidence_reference(source, context, raw_reference))

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
