import hashlib
import json

from .models import ResolveRouteRequest, RouteSignature


def discovery_context_key(request: ResolveRouteRequest) -> str | None:
    context = request.discovery_context
    if not context.has_terms():
        return None
    payload = {
        "entity_terms": [value.casefold() for value in context.entity_terms],
        "search_terms": [value.casefold() for value in context.search_terms],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def build_route_signature(request: ResolveRouteRequest) -> RouteSignature:
    return RouteSignature(
        topic_code=request.topic_code,
        evidence_kind=request.evidence_kind,
        jurisdiction=request.jurisdiction,
        jurisdiction_key=request.jurisdiction.routing_key(),
        discovery_context_key=discovery_context_key(request),
    )


def route_key(signature: RouteSignature) -> str:
    parts = [
        "route-v2",
        signature.taxonomy_version,
        signature.topic_code.value,
        signature.evidence_kind.value,
        signature.jurisdiction_key,
    ]
    if signature.discovery_context_key:
        parts.append(f"CTX:{signature.discovery_context_key}")
    return "|".join(parts)
