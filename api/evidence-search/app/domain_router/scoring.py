ENTITY_MATCH = 1.00
CITY_MATCH = 0.90
REGION_MATCH = 0.75
COUNTRY_MATCH = 0.60
SUBCATEGORY_MATCH = 0.55
CATEGORY_MATCH = 0.45
SOURCE_TYPE_MATCH_BONUS = 0.20


def confidence_factor(kind: str, assertion: dict) -> float:
    confidence = assertion.get("context_confidence") or {}
    if kind in {"entity", "entities"}:
        return float(confidence.get("entities", 1.0) or 1.0)
    if kind in {"city", "region", "country", "location"}:
        return float(confidence.get("location", 1.0) or 1.0)
    if kind == "temporal":
        return float(confidence.get("temporal", 1.0) or 1.0)
    return 1.0
