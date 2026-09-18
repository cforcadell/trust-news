from common.routing_taxonomy import AuthorityLevel, MatchLevel

from .models import DomainProfile, RouteCandidate, RoutedSource, RouteSignature, SourceClassification


AUTHORITY = {
    AuthorityLevel.LOCAL_PRIMARY: 1.0,
    AuthorityLevel.REGIONAL_PRIMARY: 0.98,
    AuthorityLevel.NATIONAL_PRIMARY: 0.9,
    AuthorityLevel.SUPRANATIONAL_PRIMARY: 0.82,
    AuthorityLevel.INTERNATIONAL_PRIMARY: 0.76,
    AuthorityLevel.GLOBAL_PRIMARY: 0.72,
    AuthorityLevel.SECONDARY_AUTHORITATIVE: 0.55,
    AuthorityLevel.OTHER: 0.25,
    AuthorityLevel.UNKNOWN: 0.2,
}
MATCH = {MatchLevel.EXACT: 1.0, MatchLevel.PARTIAL: 0.55, MatchLevel.UNKNOWN: 0.2, MatchLevel.NONE: 0.0}


def _specificity(signature: RouteSignature, jurisdictions) -> float:
    for jurisdiction in jurisdictions:
        if jurisdiction.routing_key() == signature.jurisdiction_key:
            return 1.0
    for jurisdiction in jurisdictions:
        if signature.jurisdiction.country_code and jurisdiction.country_code == signature.jurisdiction.country_code:
            return 0.8
        if jurisdiction.scope.value in {"GLOBAL", "SUPRANATIONAL"}:
            return 0.55
    return 0.25


def classification_score(signature: RouteSignature, source: SourceClassification) -> float:
    provider = max(0.0, min(1.0, float(source.provider_score or 0)))
    score = (
        AUTHORITY[source.authority_level] * 0.30
        + _specificity(signature, source.jurisdictions) * 0.25
        + MATCH[source.evidence_kind_match] * 0.16
        + MATCH[source.topic_match] * 0.14
        + source.semantic_relevance * 0.08
        + source.classification_confidence * 0.05
        + provider * 0.02
    )
    return round(max(0.0, min(1.0, score)), 6)


def route_candidate(signature: RouteSignature, source: SourceClassification) -> RouteCandidate:
    return RouteCandidate(
        domain=source.domain,
        topic_match=source.topic_match,
        evidence_kind_match=source.evidence_kind_match,
        semantic_relevance=source.semantic_relevance,
        provider_score=source.provider_score,
        reason=source.reason,
        base_score=classification_score(signature, source),
    )


def rank_sources(
    candidates: list[RouteCandidate],
    profiles: dict[str, DomainProfile],
    language: str,
    limit: int,
) -> list[RoutedSource]:
    scored = []
    for candidate in candidates:
        profile = profiles.get(candidate.domain)
        if not profile:
            continue
        language_bonus = 0.03 if language != "unknown" and language in profile.languages else 0.0
        scored.append((min(1.0, candidate.base_score + language_bonus), candidate, profile))
    scored.sort(key=lambda item: (-item[0], item[1].domain))
    return [
        RoutedSource(
            domain=profile.domain,
            source_type=profile.source_type,
            authority_level=profile.authority_level,
            jurisdictions=profile.jurisdictions,
            topic_codes=profile.topic_codes,
            evidence_kinds=profile.evidence_kinds,
            languages=profile.languages,
            route_score=score,
            rank=index,
            reason=candidate.reason,
            profile_version=profile.profile_version,
        )
        for index, (score, candidate, profile) in enumerate(scored[:limit], 1)
    ]
