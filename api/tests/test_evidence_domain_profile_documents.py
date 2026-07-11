import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = ROOT / "api/evidence-search"
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(EVIDENCE_ROOT))

from common.category_catalog import CATEGORY_IDS
from app.domain_router.profiles_loader import (
    MIN_SUBCATEGORIES_PER_CATEGORY,
    DomainProfileNotFound,
    load_profile_from_mongo,
    load_normalization_configs,
    validate_subcategory_coverage,
)

INIT_SCRIPT = ROOT / "scripts/k8s/apis/init-evidence-search-domains.py"
spec = importlib.util.spec_from_file_location("init_evidence_search_domains", INIT_SCRIPT)
init_domains = importlib.util.module_from_spec(spec)
spec.loader.exec_module(init_domains)

OFFICIAL_GENERATOR = ROOT / "scripts/k8s/apis/generate-official-evidence-domain-profile.py"
official_spec = importlib.util.spec_from_file_location("generate_official_evidence_domain_profile", OFFICIAL_GENERATOR)
official_generator = importlib.util.module_from_spec(official_spec)
official_spec.loader.exec_module(official_generator)


class FakeCollection:
    def __init__(self, docs):
        self.docs = docs
        self.calls = []

    async def find_one(self, query, projection=None):
        self.calls.append(query)
        return next((dict(doc) for doc in self.docs if all(doc.get(k) == v for k, v in query.items())), None)


def seed_profile():
    return json.loads((EVIDENCE_ROOT / "config/evidence-domain-profile-default.json").read_text())


def seed_configs():
    return json.loads((EVIDENCE_ROOT / "config/evidence-normalization-configs.json").read_text())


def test_seed_is_one_complete_profile_and_validates_references():
    profile = seed_profile()
    configs = init_domains.load_configs(EVIDENCE_ROOT / "config/evidence-normalization-configs.json")
    init_domains.validate_profiles(profile, configs)
    docs = init_domains.build_profile_documents(profile)
    assert len(docs) == 1
    assert docs[0]["profile_id"] == "default"
    assert len(docs[0]["domains"]) == 500
    counts = {category_id: 0 for category_id in CATEGORY_IDS}
    for domain in docs[0]["domains"]:
        for category in domain["categories"]:
            counts[category["category_id"]] += 1
        assert any(location["scope"] in {"global", "macroregion", "country", "international_organization"} for location in domain["locations"])
    assert counts == {category_id: 50 for category_id in CATEGORY_IDS}


@pytest.mark.asyncio
async def test_profile_repository_loads_requested_profile():
    profile = seed_profile()
    profile["profile_id"] = "custom"
    result = await load_profile_from_mongo(FakeCollection([profile]), "custom")
    assert result.profile_id == "custom"


@pytest.mark.asyncio
async def test_profile_repository_falls_back_to_default():
    collection = FakeCollection([seed_profile()])
    result = await load_profile_from_mongo(collection, "missing")
    assert result.profile_id == "default"
    assert len(collection.calls) == 2


@pytest.mark.asyncio
async def test_profile_repository_errors_without_requested_or_default():
    with pytest.raises(DomainProfileNotFound) as exc_info:
        await load_profile_from_mongo(FakeCollection([]), "missing")
    assert exc_info.value.code == "DOMAIN_PROFILE_NOT_FOUND"


@pytest.mark.asyncio
async def test_normalization_configs_are_independent_documents():
    configs = await load_normalization_configs(FakeCollection(seed_configs()))
    assert set(configs) == {"subcategories", "location_types", "source_types"}


def test_every_category_has_at_least_ten_subcategories():
    configs = init_domains.load_configs(EVIDENCE_ROOT / "config/evidence-normalization-configs.json")
    validate_subcategory_coverage(configs["subcategories"])
    counts = {}
    for item in configs["subcategories"].items:
        if item.get("enabled", True):
            for category_id in item.get("category_ids") or []:
                counts[category_id] = counts.get(category_id, 0) + 1
    assert set(counts) == set(CATEGORY_IDS)
    assert min(counts.values()) >= MIN_SUBCATEGORIES_PER_CATEGORY


def test_official_profile_generator_rejects_forbidden_domains():
    assert official_generator.normalize_domain("https://www.wikipedia.org/wiki/Test") is None
    assert official_generator.normalize_domain("https://news.medium.com/example") is None


def test_official_profile_generator_fails_when_category_is_incomplete():
    configs = seed_configs()
    seed = [
        {
            "domain": "who.int",
            "url": "https://www.who.int/",
            "official": True,
            "category_id": 5,
            "source_types": ["official", "healthcare"],
            "locations": [{"scope": "global"}],
            "languages": ["en"],
        }
    ]
    with pytest.raises(ValueError, match="not contain enough accepted domains"):
        official_generator.build_profile(seed, configs, 1, False, "official-default")
