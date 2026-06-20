from __future__ import annotations

import unicodedata
from typing import Any, Dict

from common.models.evidence_models import EvidenceDomainProfile


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip())
    return "".join(char for char in text if not unicodedata.combining(char)).casefold()


def _location_match(assertion_locations: list[dict], domain_locations: list[dict]) -> tuple[float, str | None]:
    best = (0.0, None)
    for domain_location in domain_locations:
        scope = domain_location.get("scope")
        if scope == "global":
            best = max(best, (0.35, "global"), key=lambda item: item[0])
        for assertion_location in assertion_locations:
            if domain_location.get("region_code") and str(domain_location["region_code"]).upper() == str(assertion_location.get("region_code") or "").upper():
                best = max(best, (1.0, "region"), key=lambda item: item[0])
            elif domain_location.get("country_code") and str(domain_location["country_code"]).upper() == str(assertion_location.get("country_code") or "").upper():
                best = max(best, (0.75, "country"), key=lambda item: item[0])
            elif scope == "international_organization" and (
                _fold(domain_location.get("organization_id")) == _fold(assertion_location.get("organization_id"))
                or _fold(domain_location.get("name")) == _fold(assertion_location.get("name"))
            ):
                best = max(best, (0.85, "international_organization"), key=lambda item: item[0])
            elif scope == "macroregion" and (
                _fold(domain_location.get("macroregion_id")) == _fold(assertion_location.get("macroregion_id"))
                or _fold(domain_location.get("name")) == _fold(assertion_location.get("name"))
            ):
                best = max(best, (0.8, "macroregion"), key=lambda item: item[0])
    return best


def resolve_domains(assertion: Dict[str, Any], profile: EvidenceDomainProfile | Dict[str, Any], max_domains: int | None = None) -> Dict[str, Any]:
    if not isinstance(profile, EvidenceDomainProfile):
        profile = EvidenceDomainProfile.model_validate(profile)
    weights = profile.scoring_weights
    policy = profile.selection_policy
    category_id = assertion.get("categoryId")
    subcategory = str(assertion.get("subcategory") or "unknown").upper()
    context = assertion.get("context") or {}
    assertion_locations = context.get("locations") or []
    assertion_entities = {_fold(item.get("name")) for item in context.get("entities") or [] if item.get("name")}
    preferred_source_types = {_fold(value) for value in (assertion.get("search_hints") or {}).get("preferred_source_types") or []}
    scored = []

    for domain in profile.domains:
        if not domain.get("enabled", True):
            continue
        categories = domain.get("categories") or []
        compatible = [item for item in categories if item.get("category_id") == category_id]
        category_match = 1.0 if compatible else 0.0
        subcategory_match = 1.0 if any(subcategory in {str(value).upper() for value in item.get("subcategories") or []} for item in compatible) else 0.0
        location_match, location_reason = _location_match(assertion_locations, domain.get("locations") or [])
        source_types = {_fold(value) for value in domain.get("source_types") or []}
        source_type_match = 1.0 if source_types & preferred_source_types else 0.0
        entity_match = 1.0 if assertion_entities & {_fold(value) for value in domain.get("entities") or []} else 0.0
        official_bonus = weights.official_bonus if "official" in source_types else 0.0
        statistics_bonus = weights.statistics_bonus if "statistics" in source_types else 0.0
        has_global = any(item.get("scope") == "global" for item in domain.get("locations") or [])
        global_bonus = weights.global_location_bonus if has_global else 0.0
        raw_score = (
            float(domain.get("score") or 0.0) * weights.base_domain_score
            + category_match * weights.category_match
            + subcategory_match * weights.subcategory_match
            + location_match * weights.location_match
            + source_type_match * weights.source_type_match
            + entity_match * weights.entity_match
            + official_bonus + statistics_bonus + global_bonus
        )
        final_score = max(0.0, raw_score)
        matched = {
            "category": bool(category_match),
            "subcategory": bool(subcategory_match),
            "location": location_reason,
            "location_score": location_match,
            "source_type": bool(source_type_match),
            "entity": bool(entity_match),
        }
        scored.append({
            "domain": domain.get("domain"),
            "source_type": next(iter(domain.get("source_types") or []), "unknown"),
            "source_types": domain.get("source_types") or [],
            "base_score": float(domain.get("score") or 0.0),
            "raw_score": round(raw_score, 6),
            "final_score": round(final_score, 6),
            "weight": round(final_score, 6),
            "trust_score": float(domain.get("score") or 0.3),
            "matched": matched,
            "reason": "Weighted local domain scoring",
            "matched_profiles": [profile.profile_id],
        })

    eligible = [item for item in scored if item["final_score"] >= policy.min_score]
    eligible.sort(key=lambda item: (item["final_score"], item["base_score"], item["domain"]), reverse=True)
    limit = min(max_domains or policy.max_domains, policy.max_domains)
    selected = eligible[:limit]
    return {
        "selected_profiles": [profile.profile_id],
        "preferred_domains": selected,
        "selected_domains": selected,
        "fallback_used": not bool(selected) and policy.fallback_to_general_search,
        "min_score": policy.min_score,
        "max_domains": limit,
    }
