from .models import ResolveRouteRequest, RouteSignature


SOURCE_TYPE_TERMS = {
    "official_statistic": "official statistics statistical institute",
    "monetary_policy": "central bank official monetary policy",
    "public_health": "public health authority official data",
}


def build_discovery_queries(signature: RouteSignature, request: ResolveRouteRequest) -> list[str]:
    source_terms = SOURCE_TYPE_TERMS.get(signature.claim_type, "official primary source")
    jurisdiction = " ".join(value for value in (request.location.name, signature.region_code if signature.region_code != "*" else "", signature.country_code if signature.country_code != "GLOBAL" else "") if value and value != "unknown")
    entity = " ".join(item.name for item in request.entities[:2])
    category = str(request.category) if str(request.category).lower() != "unknown" else ""
    query = " ".join(part for part in (source_terms, category, signature.subcategory.replace("_", " "), jurisdiction, entity) if part).strip()
    return [query]
