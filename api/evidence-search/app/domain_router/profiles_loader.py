from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict

from common.category_catalog import CATEGORY_IDS
from common.models.evidence_models import EvidenceDomainProfile, EvidenceNormalizationConfig

DEFAULT_COLLECTION = "evidence_domain_profiles"
DEFAULT_NORMALIZATION_COLLECTION = "evidence_normalization_configs"
PROFILE_ID = "default"
CONFIG_TYPES = ("subcategories", "location_types", "source_types")
MIN_SUBCATEGORIES_PER_CATEGORY = 10
MIN_DEFAULT_PROFILE_DOMAINS = 1000
MIN_DEFAULT_DOMAINS_PER_CATEGORY = 100


class DomainProfileNotFound(RuntimeError):
    code = "DOMAIN_PROFILE_NOT_FOUND"

    def __init__(self, profile_id: str):
        self.profile_id = profile_id
        super().__init__(f"No evidence domain profile found for profile_id={profile_id} and default profile is missing.")


def profile_version(profile: EvidenceDomainProfile, configs: Dict[str, EvidenceNormalizationConfig]) -> str:
    config_versions = ",".join(f"{key}:{configs[key].version}" for key in sorted(configs))
    return f"{profile.profile_id}:{profile.version}|{config_versions}"


async def load_profile_from_mongo(collection, profile_id: str = PROFILE_ID) -> EvidenceDomainProfile:
    if collection is None:
        raise RuntimeError("Evidence domain profile collection is not initialized")
    requested = str(profile_id or PROFILE_ID).strip() or PROFILE_ID
    doc = await collection.find_one({"profile_id": requested, "enabled": True}, {"_id": 0})
    if not doc and requested != PROFILE_ID:
        doc = await collection.find_one({"profile_id": PROFILE_ID, "enabled": True}, {"_id": 0})
    if not doc:
        raise DomainProfileNotFound(requested)
    return EvidenceDomainProfile.model_validate(doc)


async def load_normalization_configs(collection) -> Dict[str, EvidenceNormalizationConfig]:
    if collection is None:
        raise RuntimeError("Evidence normalization config collection is not initialized")
    configs: Dict[str, EvidenceNormalizationConfig] = {}
    for config_type in CONFIG_TYPES:
        doc = await collection.find_one({"config_type": config_type, "enabled": True}, {"_id": 0})
        if not doc:
            raise RuntimeError(f"Evidence normalization config not found for config_type={config_type}")
        configs[config_type] = EvidenceNormalizationConfig.model_validate(doc)
    return configs


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip())
    return "".join(char for char in text if not unicodedata.combining(char)).casefold()


def _alias_map(items: list[dict]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items:
        if not item.get("enabled", True):
            continue
        canonical = str(item.get("id") or "").strip()
        for value in [canonical, item.get("name"), *(item.get("aliases") or [])]:
            if value:
                result[_fold(value)] = canonical
    return result


def normalize_assertion(assertion: Dict[str, Any], configs: Dict[str, EvidenceNormalizationConfig]) -> Dict[str, Any]:
    normalized = dict(assertion)
    category_id = int(normalized.get("categoryId"))
    sub_doc = configs["subcategories"].model_dump(mode="json")
    sub_map = _alias_map(sub_doc.get("items") or [])
    raw_subcategory = normalized.get("subcategory")
    canonical_subcategory = sub_map.get(_fold(raw_subcategory), "unknown")
    allowed = next((item.get("category_ids") or [] for item in sub_doc.get("items") or [] if item.get("id") == canonical_subcategory), [])
    normalized["subcategory"] = canonical_subcategory if category_id in allowed else "unknown"

    source_doc = configs["source_types"].model_dump(mode="json")
    source_map = _alias_map(source_doc.get("items") or [])
    hints = dict(normalized.get("search_hints") or {})
    hints["preferred_source_types"] = list(dict.fromkeys(
        source_map.get(_fold(value), "unknown") for value in hints.get("preferred_source_types") or []
    ))
    normalized["search_hints"] = hints

    location_doc = configs["location_types"].model_dump(mode="json")
    scope_map = _alias_map(location_doc.get("scopes") or [])
    organization_map = _alias_map(location_doc.get("organizations") or [])
    context = dict(normalized.get("context") or {})
    locations = []
    for raw in context.get("locations") or []:
        location = dict(raw)
        scope = scope_map.get(_fold(location.get("scope") or location.get("type")), "")
        if not scope:
            if location.get("region_code"):
                scope = "region"
            elif location.get("country_code"):
                scope = "country"
            elif organization_map.get(_fold(location.get("name"))):
                scope = "international_organization"
        if not scope:
            continue
        location.pop("type", None)
        location["scope"] = scope
        if location.get("country_code"):
            location["country_code"] = str(location["country_code"]).upper()
        if location.get("region_code"):
            location["region_code"] = str(location["region_code"]).upper()
        organization_id = organization_map.get(_fold(location.get("name")))
        if organization_id:
            location["organization_id"] = organization_id
        locations.append(location)
    context["locations"] = locations
    normalized["context"] = context
    return normalized


def validate_subcategory_coverage(config: EvidenceNormalizationConfig) -> None:
    counts = {category_id: 0 for category_id in CATEGORY_IDS}
    for item in config.items:
        if not item.get("enabled", True):
            continue
        for category_id in item.get("category_ids") or []:
            if category_id not in CATEGORY_IDS:
                raise ValueError(f"Unknown category_id={category_id} in subcategories config")
            counts[category_id] += 1
    incomplete = {key: value for key, value in sorted(counts.items()) if value < MIN_SUBCATEGORIES_PER_CATEGORY}
    if incomplete:
        raise ValueError(
            f"Each category requires at least {MIN_SUBCATEGORIES_PER_CATEGORY} enabled subcategories; "
            f"incomplete={incomplete}"
        )


def validate_profile_references(profile: EvidenceDomainProfile, configs: Dict[str, EvidenceNormalizationConfig]) -> None:
    validate_subcategory_coverage(configs["subcategories"])
    subcategories = {item.get("id") for item in configs["subcategories"].items if item.get("enabled", True)}
    source_types = {item.get("id") for item in configs["source_types"].items if item.get("enabled", True)}
    scopes = {item.get("id") for item in configs["location_types"].scopes if item.get("enabled", True)}
    expected_versions = profile.normalization_versions
    for config_type, config in configs.items():
        if str(expected_versions.get(config_type)) != str(config.version):
            raise ValueError(f"Normalization version mismatch for config_type={config_type}")
    seen_domains = set()
    category_counts = {category_id: 0 for category_id in CATEGORY_IDS}
    for domain in profile.domains:
        domain_name = str(domain.get("domain") or "").strip().lower()
        if not re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z]{2,}", domain_name):
            raise ValueError(f"Invalid normalized domain={domain_name}")
        if domain_name in seen_domains:
            raise ValueError(f"Duplicated domain={domain_name}")
        seen_domains.add(domain_name)
        if "locarions" in domain or "language" in domain:
            raise ValueError(f"Legacy domain fields are not supported for domain={domain_name}")
        if "source_type" in domain:
            raise ValueError(f"Legacy source_type is not supported for domain={domain.get('domain')}")
        for source_type in domain.get("source_types") or []:
            if source_type not in source_types:
                raise ValueError(f"Unknown source_type={source_type} for domain={domain.get('domain')}")
        for category in domain.get("categories") or []:
            category_id = category.get("category_id")
            if category_id not in CATEGORY_IDS:
                raise ValueError(f"Unknown category_id={category.get('category_id')} for domain={domain.get('domain')}")
            category_counts[category_id] += 1
            unknown = set(category.get("subcategories") or []) - subcategories
            if unknown:
                raise ValueError(f"Unknown subcategories={sorted(unknown)} for domain={domain.get('domain')}")
        for location in domain.get("locations") or []:
            if location.get("scope") not in scopes:
                raise ValueError(f"Unknown location scope={location.get('scope')} for domain={domain.get('domain')}")
    if profile.profile_id == PROFILE_ID:
        if len(seen_domains) < MIN_DEFAULT_PROFILE_DOMAINS:
            raise ValueError(f"Default profile requires at least {MIN_DEFAULT_PROFILE_DOMAINS} unique domains")
        incomplete = {key: value for key, value in sorted(category_counts.items()) if value < MIN_DEFAULT_DOMAINS_PER_CATEGORY}
        if incomplete:
            raise ValueError(
                f"Default profile requires at least {MIN_DEFAULT_DOMAINS_PER_CATEGORY} domains per category; "
                f"incomplete={incomplete}"
            )


async def load_profile_bundle(profile_collection, normalization_collection, profile_id: str = PROFILE_ID):
    profile = await load_profile_from_mongo(profile_collection, profile_id)
    configs = await load_normalization_configs(normalization_collection)
    validate_profile_references(profile, configs)
    return profile, configs, profile_version(profile, configs)
