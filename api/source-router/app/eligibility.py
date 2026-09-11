from .models import RouteSignature, SourceClassification


def is_eligible(signature: RouteSignature, source: SourceClassification) -> bool:
    jurisdiction = source.jurisdiction
    scope = jurisdiction.scope.lower()
    authority = source.authority_level.lower()

    if signature.country_code == "GLOBAL":
        return scope in {"global", "international", "supranational"} or authority in {"global_primary", "international_primary"}
    if scope in {"global", "international"}:
        return True
    if scope in {"supranational", "european"}:
        return (
            jurisdiction.country_code == signature.country_code
            or signature.country_code in jurisdiction.applicable_country_codes
        )
    if jurisdiction.country_code and jurisdiction.country_code != signature.country_code:
        return False
    if jurisdiction.region_code:
        if signature.region_code == "*":
            return jurisdiction.country_code == signature.country_code
        return jurisdiction.region_code == signature.region_code
    if scope in {"national", "country"} or authority == "national_primary":
        return jurisdiction.country_code == signature.country_code
    if scope in {"regional", "local"} or authority in {"regional_primary", "local_primary"}:
        return signature.region_code != "*" and jurisdiction.region_code == signature.region_code
    return bool(jurisdiction.country_code == signature.country_code and source.classification_confidence >= 0.5)


def eligible_sources(signature: RouteSignature, sources: list[SourceClassification]) -> list[SourceClassification]:
    return [source for source in sources if is_eligible(signature, source)]
