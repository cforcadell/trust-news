from .models import RouteSignature, RoutedSource, SourceClassification


AUTHORITY = {
    "regional_primary": 1.0, "local_primary": 0.98, "national_primary": 0.9,
    "supranational_primary": 0.8, "international_primary": 0.72, "global_primary": 0.7,
}
MATCH = {"exact": 1.0, "partial": 0.55, "unknown": 0.2, "none": 0.0}


def _specificity(signature: RouteSignature, source: SourceClassification) -> float:
    jurisdiction = source.jurisdiction
    if signature.region_code != "*" and jurisdiction.region_code == signature.region_code:
        return 1.0
    if jurisdiction.country_code == signature.country_code:
        return 0.8
    if jurisdiction.scope.lower() in {"supranational", "european"}:
        return 0.55
    return 0.4


def routing_score(signature: RouteSignature, source: SourceClassification) -> float:
    provider = max(0.0, min(1.0, float(source.provider_score or 0)))
    score = (
        AUTHORITY.get(source.authority_level.lower(), 0.3) * 0.28
        + _specificity(signature, source) * 0.24
        + MATCH.get(source.claim_type_match.lower(), 0.2) * 0.13
        + MATCH.get(source.subcategory_match.lower(), 0.2) * 0.10
        + MATCH.get(source.entity_match.lower(), 0.2) * 0.04
        + MATCH.get(source.language_match.lower(), 0.2) * 0.03
        + source.semantic_relevance * 0.10
        + source.classification_confidence * 0.05
        + provider * 0.03
    )
    return round(max(0.0, min(1.0, score)), 6)


def rank_sources(signature: RouteSignature, sources: list[SourceClassification], limit: int) -> list[RoutedSource]:
    ordered = sorted(sources, key=lambda item: (-routing_score(signature, item), item.domain))[:limit]
    return [RoutedSource(**item.model_dump(), rank=index, routing_score=routing_score(signature, item)) for index, item in enumerate(ordered, 1)]
