from __future__ import annotations

from typing import Any, Dict, List

try:
    from .scoring import (
        CATEGORY_MATCH,
        CITY_MATCH,
        COUNTRY_MATCH,
        ENTITY_MATCH,
        REGION_MATCH,
        SOURCE_TYPE_MATCH_BONUS,
        SUBCATEGORY_MATCH,
        confidence_factor,
    )
except ImportError:
    from scoring import (
        CATEGORY_MATCH,
        CITY_MATCH,
        COUNTRY_MATCH,
        ENTITY_MATCH,
        REGION_MATCH,
        SOURCE_TYPE_MATCH_BONUS,
        SUBCATEGORY_MATCH,
        confidence_factor,
    )


def _profiles_for_assertion(assertion: Dict[str, Any]) -> list[tuple[str, str, float, str]]:
    """Extract candidate profile lookups from an enriched assertion."""
    # Category and subcategory matches provide broad topical routing signals.
    profiles: list[tuple[str, str, float, str]] = []
    category_id = assertion.get("categoryId")
    if category_id is not None:
        key = str(category_id)
        profiles.append(("categories", key, CATEGORY_MATCH, f"category_{key}"))
    subcategory = assertion.get("subcategory")
    if category_id is not None and subcategory not in (None, "", "unknown"):
        key = f"{category_id}.{subcategory}"
        profiles.append(("subcategories", key, SUBCATEGORY_MATCH, f"subcategory_{category_id}_{subcategory}"))

    # Location matches become more specific from country to region to city.
    context = assertion.get("context") or {}
    for loc in context.get("locations") or []:
        country = loc.get("country_code")
        region = loc.get("region_code")
        city = loc.get("city")
        if country:
            profiles.append(("countries", str(country).upper(), COUNTRY_MATCH * confidence_factor("location", assertion), f"country_{str(country).upper()}"))
        if region:
            profiles.append(("regions", str(region).upper(), REGION_MATCH * confidence_factor("location", assertion), f"region_{str(region).upper()}"))
        if region and city:
            key = f"{str(region).upper()}-{city}"
            profiles.append(("cities", key, CITY_MATCH * confidence_factor("location", assertion), f"city_{key}"))

    # Entity matches are the strongest signal because they often map to official sources.
    for ent in context.get("entities") or []:
        name = ent.get("name")
        if name:
            profiles.append(("entities", str(name), ENTITY_MATCH * confidence_factor("entities", assertion), f"entity_{str(name).replace(' ', '_')}"))
    return profiles


def resolve_domains(assertion: Dict[str, Any], profiles: Dict[str, Any], max_domains: int = 8) -> Dict[str, Any]:
    """Resolve preferred evidence domains for an assertion from profile matches."""
    # Prepare accumulators for matched profile names and per-domain scoring.
    selected_profiles: list[str] = []
    merged: dict[str, dict[str, Any]] = {}
    preferred_source_types = set((assertion.get("search_hints") or {}).get("preferred_source_types") or [])
    source_types = profiles.get("source_types") or {}

    # Evaluate every candidate profile lookup derived from the assertion.
    for section, key, base_score, profile_name in _profiles_for_assertion(assertion):
        profile = (profiles.get(section) or {}).get(key)
        if not profile:
            continue
        selected_profiles.append(profile_name)

        # Score and merge each preferred domain exposed by the matched profile.
        for domain_cfg in profile.get("preferred_domains") or []:
            domain = str(domain_cfg.get("domain", "")).lower().strip()
            if not domain:
                continue
            source_type = domain_cfg.get("source_type", "unknown")
            bonus = SOURCE_TYPE_MATCH_BONUS if source_type in preferred_source_types else 0.0
            weight = float(domain_cfg.get("weight", 0.0) or 0.0)
            score = max(0.0, min(1.0, base_score * weight + bonus))
            trust_score = float((source_types.get(source_type) or {}).get("default_trust_score", 0.3) or 0.3)
            existing = merged.get(domain)
            matched_profile = profile_name

            # If multiple profiles point to the same domain, keep the strongest metadata.
            if existing:
                existing["weight"] = max(existing["weight"], score)
                existing["trust_score"] = max(existing["trust_score"], trust_score)
                existing.setdefault("matched_profiles", []).append(matched_profile)
                existing["reason"] = f"Matched {', '.join(dict.fromkeys(existing['matched_profiles']))}"
            else:
                merged[domain] = {
                    "domain": domain,
                    "source_type": source_type,
                    "weight": round(score, 4),
                    "trust_score": trust_score,
                    "reason": domain_cfg.get("reason") or f"Matched {matched_profile}",
                    "matched_profiles": [matched_profile],
                }

    # Rank by contextual score, number of matched profiles, and trust score.
    preferred_domains = sorted(
        merged.values(),
        key=lambda item: (item["weight"], len(item.get("matched_profiles", [])), item["trust_score"]),
        reverse=True,
    )[:max_domains]

    # Return router metadata that can be logged, cached, and attached to evidence.
    return {
        "selected_profiles": list(dict.fromkeys(selected_profiles)),
        "preferred_domains": preferred_domains,
        "fallback_used": not bool(preferred_domains),
    }
