from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

DEFAULT_COLLECTION = "evidence_domain_profiles"
PROFILE_ID = "default"
PROFILE_INDEX_DOC_TYPE = "profile_index"
PROFILE_SUBSET_DOC_TYPE = "profile_subset"
PROFILE_SUBSETS = ("source_types", "categories", "subcategories", "countries", "regions", "cities", "entities")


def iso(dt: datetime) -> str:
    """Serialize datetimes as UTC ISO-8601 strings."""
    # Profile versions are compared as strings, so always normalize timezone first.
    return dt.astimezone(timezone.utc).isoformat()


def profile_version_from_index(doc: Dict[str, Any]) -> str:
    """Derive a stable profile version from the profile index document."""
    # Prefer updated_at, then explicit version, then profile id as a final fallback.
    raw = doc.get("updated_at") or doc.get("version") or doc.get("profile_id") or PROFILE_ID

    # Datetime values need serialization before being used in cache keys.
    if isinstance(raw, datetime):
        return iso(raw)
    return str(raw)


def assemble_profiles_from_subset_docs(docs: list[Dict[str, Any]], profile_id: str = PROFILE_ID) -> Dict[str, Any]:
    """Reassemble a full profile bundle from per-subset Mongo documents."""
    # Collect only the requested profile subset documents and ignore unrelated rows.
    profiles: Dict[str, Any] = {}
    for doc in docs:
        if doc.get("doc_type") != PROFILE_SUBSET_DOC_TYPE or doc.get("profile_id") != profile_id:
            continue
        subset = doc.get("subset")
        if subset in PROFILE_SUBSETS:
            profiles[subset] = doc.get("items") or {}

    # Fail fast if the database is missing required subsets for routing.
    missing = [subset for subset in PROFILE_SUBSETS if subset not in profiles]
    if missing:
        raise RuntimeError(f"Missing evidence domain profile subsets for profile_id={profile_id}: {', '.join(missing)}")
    if not profiles.get("source_types"):
        raise RuntimeError(f"Evidence domain profile source_types is empty for profile_id={profile_id}")
    return profiles


async def load_profiles_from_mongo(collection, profile_id: str = PROFILE_ID) -> tuple[Dict[str, Any], str]:
    """Load a complete profile bundle and its version from MongoDB."""
    # The collection is injected by the FastAPI startup lifecycle.
    if collection is None:
        raise RuntimeError("Evidence domain profile collection is not initialized")

    # Read the profile index first because it provides versioning for cache keys.
    index_doc = await collection.find_one(
        {"doc_type": PROFILE_INDEX_DOC_TYPE, "profile_id": profile_id},
        {"_id": 0},
    )
    if not index_doc:
        raise RuntimeError(f"Evidence domain profile index not found for profile_id={profile_id}")

    # Load every subset document for the profile and assemble the in-memory bundle.
    subset_docs = await collection.find(
        {"doc_type": PROFILE_SUBSET_DOC_TYPE, "profile_id": profile_id},
        {"_id": 0},
    ).to_list(length=None)
    profiles = assemble_profiles_from_subset_docs(subset_docs, profile_id=profile_id)
    return profiles, profile_version_from_index(index_doc)


def minimal_default_profiles() -> Dict[str, Any]:
    """Return a tiny built-in profile set for tests or emergency fallback usage."""
    # Include enough source types and topic mappings to exercise the domain router.
    return {
        "source_types": {
            "official": {"default_trust_score": 1.0},
            "public_registry": {"default_trust_score": 0.95},
            "statistics": {"default_trust_score": 0.95},
            "reputable_media": {"default_trust_score": 0.70},
            "unknown": {"default_trust_score": 0.30},
        },
        "categories": {
            "1": {"preferred_domains": [{"domain": "ine.es", "source_type": "statistics", "weight": 0.90, "reason": "Spanish official statistics source"}]},
            "5": {"preferred_domains": [{"domain": "who.int", "source_type": "official", "weight": 0.95, "reason": "World Health Organization"}]},
        },
        "subcategories": {
            "1.EMPLOYMENT": {"preferred_domains": [{"domain": "sepe.es", "source_type": "official", "weight": 0.90, "reason": "Spanish public employment service"}]},
        },
        "countries": {},
        "regions": {},
        "cities": {},
        "entities": {},
    }
