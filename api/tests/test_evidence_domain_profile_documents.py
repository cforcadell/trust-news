import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INIT_SCRIPT = ROOT / "scripts" / "k8s" / "apis" / "init-evidence-search-domains.py"
PROFILES_LOADER_ROOT = ROOT / "api" / "evidence-search" / "app" / "domain_router"
sys.path.insert(0, str(PROFILES_LOADER_ROOT))

spec = importlib.util.spec_from_file_location("init_evidence_search_domains", INIT_SCRIPT)
init_domains = importlib.util.module_from_spec(spec)
spec.loader.exec_module(init_domains)

loader_spec = importlib.util.spec_from_file_location("domain_profiles_loader", PROFILES_LOADER_ROOT / "profiles_loader.py")
profiles_loader = importlib.util.module_from_spec(loader_spec)
loader_spec.loader.exec_module(profiles_loader)


def sample_profiles():
    return {
        "source_types": {"official": {"default_trust_score": 1.0}, "statistics": {"default_trust_score": 0.95}},
        "categories": {
            "ECONOMY": {
                "preferred_domains": [
                    {"domain": "ine.es", "source_type": "statistics", "weight": 0.9, "reason": "stats"}
                ]
            }
        },
        "subcategories": {},
        "countries": {},
        "regions": {},
        "cities": {},
        "entities": {},
    }


def test_build_profile_documents_splits_profile_into_index_and_subset_docs():
    docs = init_domains.build_profile_documents(sample_profiles(), source="seed.yaml", updated_at="2026-01-01T00:00:00+00:00")

    assert len(docs) == 8
    assert docs[0]["doc_type"] == "profile_index"
    assert docs[0]["profile_id"] == "default"
    assert docs[0]["subsets"] == list(init_domains.PROFILE_SUBSETS)
    subset_docs = [doc for doc in docs if doc["doc_type"] == "profile_subset"]
    assert {doc["subset"] for doc in subset_docs} == set(init_domains.PROFILE_SUBSETS)
    assert next(doc for doc in subset_docs if doc["subset"] == "categories")["items"]["ECONOMY"]


def test_assemble_profiles_from_documents_round_trips_subsets():
    profiles = sample_profiles()
    docs = init_domains.build_profile_documents(profiles, updated_at="2026-01-01T00:00:00+00:00")

    assert init_domains.assemble_profiles_from_documents(docs) == profiles
    assert profiles_loader.assemble_profiles_from_subset_docs(docs) == profiles


def test_assemble_profiles_from_documents_rejects_missing_subset():
    docs = init_domains.build_profile_documents(sample_profiles(), updated_at="2026-01-01T00:00:00+00:00")
    docs = [doc for doc in docs if doc.get("subset") != "entities"]

    try:
        init_domains.assemble_profiles_from_documents(docs)
    except ValueError as exc:
        assert "entities" in str(exc)
    else:
        raise AssertionError("missing subset should fail")
