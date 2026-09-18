from common.routing_taxonomy import AuthorityLevel, EVIDENCE_SOURCE_TYPES, JurisdictionScope, MatchLevel

from .models import RouteSignature, SourceClassification


def jurisdiction_is_eligible(signature: RouteSignature, source: SourceClassification) -> bool:
    target = signature.jurisdiction
    for jurisdiction in source.jurisdictions:
        if jurisdiction.scope == JurisdictionScope.GLOBAL:
            return True
        if jurisdiction.scope == JurisdictionScope.SUPRANATIONAL:
            if target.scope == JurisdictionScope.SUPRANATIONAL:
                if jurisdiction.jurisdiction_code == target.jurisdiction_code:
                    return True
            elif target.country_code in jurisdiction.applicable_country_codes:
                return True
            continue
        if target.scope == JurisdictionScope.GLOBAL:
            continue
        if target.scope == JurisdictionScope.UNKNOWN:
            continue
        if target.scope == JurisdictionScope.SUPRANATIONAL:
            continue
        if jurisdiction.country_code != target.country_code:
            continue
        if jurisdiction.scope == JurisdictionScope.COUNTRY:
            return True
        if target.scope == JurisdictionScope.COUNTRY:
            continue
        if jurisdiction.region_code == target.region_code:
            return True
    return False


def is_eligible(signature: RouteSignature, source: SourceClassification) -> bool:
    if source.topic_match == MatchLevel.NONE or source.evidence_kind_match == MatchLevel.NONE:
        return False
    if source.source_type not in EVIDENCE_SOURCE_TYPES[signature.evidence_kind]:
        return False
    if not jurisdiction_is_eligible(signature, source):
        return False
    return source.authority_level not in {AuthorityLevel.UNKNOWN, AuthorityLevel.OTHER}


def eligible_sources(signature: RouteSignature, sources: list[SourceClassification]) -> list[SourceClassification]:
    return [source for source in sources if is_eligible(signature, source)]
