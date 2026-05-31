from __future__ import annotations

from typing import Any, Dict, Optional

DEFAULT_COLLECTION = "evidence_domain_profiles"
PROFILE_ID = "default"


async def load_profiles_from_mongo(collection) -> Optional[Dict[str, Any]]:
    if collection is None:
        return None
    doc = await collection.find_one({"profile_id": PROFILE_ID}, {"_id": 0})
    if not doc:
        return None
    return doc.get("profiles") or doc


def minimal_default_profiles() -> Dict[str, Any]:
    return {
        "source_types": {
            "official": {"default_trust_score": 1.0},
            "public_registry": {"default_trust_score": 0.95},
            "statistics": {"default_trust_score": 0.95},
            "reputable_media": {"default_trust_score": 0.70},
            "unknown": {"default_trust_score": 0.30},
        },
        "categories": {
            "ECONOMY": {"preferred_domains": [{"domain": "ine.es", "source_type": "statistics", "weight": 0.90, "reason": "Spanish official statistics source"}]},
            "HEALTH": {"preferred_domains": [{"domain": "who.int", "source_type": "official", "weight": 0.95, "reason": "World Health Organization"}]},
        },
        "subcategories": {
            "ECONOMY.EMPLOYMENT": {"preferred_domains": [{"domain": "sepe.es", "source_type": "official", "weight": 0.90, "reason": "Spanish public employment service"}]},
        },
        "countries": {},
        "regions": {},
        "cities": {},
        "entities": {},
    }
