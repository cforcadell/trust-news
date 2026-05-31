import importlib.util
from pathlib import Path
from types import SimpleNamespace

MODULE_PATH = Path(__file__).resolve().parents[1] / "evidence-search" / "main.py"
spec = importlib.util.spec_from_file_location("evidence_search_main", MODULE_PATH)
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


def enriched_assertion():
    return {
        "assertion_id": 1,
        "text": "El paro en Barcelona bajo en 2024.",
        "context": {
            "locations": [{"name": "Barcelona"}],
            "entities": [{"name": "INE"}],
            "temporal_context": [{"value": "2024"}],
        },
        "search_hints": {"search_keywords": ["estadistica oficial"], "suggested_queries": []},
    }


def test_excerpt_prefers_raw_content_and_is_limited():
    raw = " palabra " * 300
    excerpt = evidence.useful_excerpt({"raw_content": raw, "content": "fallback"})
    assert len(excerpt) <= 900
    assert "palabra" in excerpt


def test_source_classification_for_v2_fallbacks():
    assert evidence.source_type_for_domain("www.who.int") == "official"
    assert evidence.source_type_for_domain("reuters.com") == "news_agency"
    assert evidence.source_type_for_domain("example.com") == "media"


def test_build_queries_v2_uses_preferred_domains_and_general_fallback():
    policy = SimpleNamespace(max_queries_per_domain=2, fallback_to_general_search=True)
    domain_resolution = {
        "preferred_domains": [
            {"domain": "ine.es"},
            {"domain": "sepe.es"},
        ]
    }

    queries = evidence.build_queries_v2(enriched_assertion(), domain_resolution, policy)

    assert queries[0].startswith("site:ine.es El paro")
    assert queries[1].startswith("site:sepe.es El paro")
    assert queries[-1].startswith("El paro")


def test_build_queries_v2_skips_site_queries_when_preferred_domains_disabled():
    policy = SimpleNamespace(max_queries_per_domain=2, fallback_to_general_search=True)
    domain_resolution = evidence.empty_domain_resolution()

    queries = evidence.build_queries_v2(enriched_assertion(), domain_resolution, policy)

    assert queries
    assert all(not query.startswith("site:") for query in queries)
    assert queries[0].startswith("El paro")


def test_evidence_from_source_v2_preserves_domain_resolution_metadata():
    domain_resolution = {
        "preferred_domains": [
            {
                "domain": "ine.es",
                "source_type": "statistics",
                "trust_score": 0.95,
                "reason": "entity",
                "matched_profiles": ["entity_INE"],
            }
        ]
    }

    result = evidence.evidence_from_source_v2(
        {"url": "https://ine.es/demo", "title": "INE", "content": "Evidence text"},
        1,
        domain_resolution,
    )

    assert result["domain"] == "ine.es"
    assert result["source_type"] == "statistics"
    assert result["trust_score"] == 0.95
    assert result["why_selected"] == "entity"
    assert result["matched_profiles"] == ["entity_INE"]


def test_evidence_cache_key_normalizes_text_and_uses_profile_version():
    policy = SimpleNamespace(max_domains=8, max_results=5, max_queries_per_domain=2, fallback_to_general_search=True)
    assertion_a = {**enriched_assertion(), "text": "  El   Paro en Barcelona bajo en 2024. "}
    assertion_b = {**enriched_assertion(), "text": "el paro en barcelona bajo en 2024."}

    key_a = evidence.evidence_cache_key(assertion_a, policy, "v1")
    key_b = evidence.evidence_cache_key(assertion_b, policy, "v1")
    key_c = evidence.evidence_cache_key(assertion_b, policy, "v2")

    assert key_a == key_b
    assert key_a != key_c
    assert len(key_a) == 64
