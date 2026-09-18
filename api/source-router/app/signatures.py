from .models import ResolveRouteRequest, RouteSignature


def build_route_signature(request: ResolveRouteRequest) -> RouteSignature:
    return RouteSignature(
        topic_code=request.topic_code,
        evidence_kind=request.evidence_kind,
        jurisdiction=request.jurisdiction,
        jurisdiction_key=request.jurisdiction.routing_key(),
    )


def route_key(signature: RouteSignature) -> str:
    return "|".join((
        "route-v2",
        signature.taxonomy_version,
        signature.topic_code.value,
        signature.evidence_kind.value,
        signature.jurisdiction_key,
    ))
