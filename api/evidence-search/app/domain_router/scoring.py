ENTITY_MATCH = 1.00
CITY_MATCH = 0.90
REGION_MATCH = 0.75
COUNTRY_MATCH = 0.60
SUBCATEGORY_MATCH = 0.55
CATEGORY_MATCH = 0.45
SOURCE_TYPE_MATCH_BONUS = 0.20


def confidence_factor(kind: str, assertion: dict) -> float:
    """Return the confidence multiplier for a context dimension in an assertion."""
    # Context enrichment may attach confidence scores for entities, locations, or time.
    confidence = assertion.get("context_confidence") or {}

    # Entity confidence controls matches derived from named entities.
    if kind in {"entity", "entities"}:
        return float(confidence.get("entities", 1.0) or 1.0)

    # Location confidence controls city, region, and country domain-routing matches.
    if kind in {"city", "region", "country", "location"}:
        return float(confidence.get("location", 1.0) or 1.0)

    # Temporal confidence is currently exposed for future scoring extensions.
    if kind == "temporal":
        return float(confidence.get("temporal", 1.0) or 1.0)

    # Unknown dimensions should not penalize scoring.
    return 1.0
