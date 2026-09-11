import re

from .models import ResolveRouteRequest, RouteSignature


def _stable(value: object, default: str) -> str:
    text = re.sub(r"\s+", "_", str(value or default).strip()).upper()
    return text or default


def build_route_signature(request: ResolveRouteRequest) -> RouteSignature:
    return RouteSignature(
        claim_type=_stable(request.claim_type, "GENERAL").lower(),
        subcategory=_stable(request.subcategory, "UNKNOWN"),
        country_code=_stable(request.location.country_code, "GLOBAL"),
        region_code=_stable(request.location.region_code, "*"),
    )


def route_key(signature: RouteSignature) -> str:
    return "|".join((signature.claim_type, signature.subcategory, signature.country_code, signature.region_code))
