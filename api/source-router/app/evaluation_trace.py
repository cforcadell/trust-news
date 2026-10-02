"""Read-only descriptions of Router decisions for evaluation responses."""

from common.routing_taxonomy import AuthorityLevel, EVIDENCE_SOURCE_TYPES, MatchLevel

from .eligibility import jurisdiction_is_eligible
from .ranking import AUTHORITY, MATCH, _specificity


def rejection_reasons(signature, source):
    """Explain the same predicates used by is_eligible without altering selection."""
    reasons = []
    if source.topic_match == MatchLevel.NONE:
        reasons.append("TOPIC_MISMATCH")
    if source.evidence_kind_match == MatchLevel.NONE:
        reasons.append("EVIDENCE_KIND_MISMATCH")
    if source.source_type not in EVIDENCE_SOURCE_TYPES[signature.evidence_kind]:
        reasons.append("SOURCE_TYPE_INELIGIBLE")
    if not jurisdiction_is_eligible(signature, source):
        reasons.append("JURISDICTION_MISMATCH")
    if source.authority_level in {AuthorityLevel.UNKNOWN, AuthorityLevel.OTHER}:
        reasons.append("AUTHORITY_INELIGIBLE")
    return reasons


def classification_score_components(signature, source):
    """Show the terms of classification_score; the production scorer remains unchanged."""
    provider = max(0.0, min(1.0, float(source.provider_score or 0)))
    values = {
        "authority": AUTHORITY[source.authority_level] * 0.30,
        "jurisdiction_specificity": _specificity(signature, source.jurisdictions) * 0.25,
        "evidence_kind_match": MATCH[source.evidence_kind_match] * 0.16,
        "topic_match": MATCH[source.topic_match] * 0.14,
        "semantic_relevance": source.semantic_relevance * 0.08,
        "classification_confidence": source.classification_confidence * 0.05,
        "provider_score": provider * 0.02,
    }
    return {key: round(value, 6) for key, value in values.items()}


def ranking_rows(route, profiles, language, selected):
    """Describe candidate ranking from the exact route/profile snapshot used by rank_sources."""
    selected_ranks = {source.domain: source.rank for source in selected}
    rows = []
    for candidate in route.candidates:
        profile = profiles.get(candidate.domain)
        bonus = 0.03 if profile and language != "unknown" and language in profile.languages else 0.0
        rows.append({
            "domain": candidate.domain,
            "base_score": candidate.base_score,
            "language_bonus": bonus,
            "route_score": min(1.0, candidate.base_score + bonus) if profile else None,
            "rank": selected_ranks.get(candidate.domain),
            "decision": "SELECTED" if candidate.domain in selected_ranks else
                        "PROFILE_MISSING" if profile is None else "RANK_LIMIT",
            "classification_components": "NOT_STORED_IN_ROUTE",
        })
    return rows
