import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

EVIDENCE_SEARCH_ROOT = Path(__file__).resolve().parents[1] / "evidence-search"
if str(EVIDENCE_SEARCH_ROOT) not in sys.path:
    sys.path.insert(0, str(EVIDENCE_SEARCH_ROOT))

from app.search import providers as search_providers

MODULE_PATH = EVIDENCE_SEARCH_ROOT / "main.py"
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
    assert result["source_id"] == "source-1"
    assert result["snippet"] == "Evidence text"
    assert result["source_type"] == "statistics"
    assert result["trust_score"] == 0.95
    assert result["why_selected"] == "entity"
    assert result["matched_profiles"] == ["entity_INE"]


def test_exa_result_normalization_uses_highlights_and_preserves_text():
    result = search_providers.normalize_exa_result({
        "url": "https://idescat.cat/demo",
        "title": "Idescat demo",
        "highlights": ["  Population reached 8 million.  ", " Official estimate. "],
        "text": "Longer page text with the full statistical context.",
        "summary": "Short summary",
        "score": 0.9,
    })

    assert result["url"] == "https://idescat.cat/demo"
    assert result["title"] == "Idescat demo"
    assert result["content"] == "Population reached 8 million. Official estimate."
    assert result["raw_content"] == "Longer page text with the full statistical context."
    assert result["summary"] == "Short summary"


def test_tavily_result_normalization_uses_content_and_preserves_raw_content():
    result = search_providers.normalize_tavily_result({
        "url": "https://tavily.example/demo",
        "title": "Tavily demo",
        "content": "  Search snippet from Tavily.  ",
        "raw_content": "  Longer extracted Tavily page text.  ",
        "score": 0.8,
    })

    assert result["content"] == "Search snippet from Tavily."
    assert result["raw_content"] == "Longer extracted Tavily page text."


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


def test_evidence_cache_key_changes_with_search_provider(monkeypatch):
    policy = SimpleNamespace(max_domains=8, max_results=5, max_queries_per_domain=2, fallback_to_general_search=True)

    monkeypatch.setattr(evidence, "SEARCH_PROVIDER", "exa")
    exa_key = evidence.evidence_cache_key(enriched_assertion(), policy, "v1")

    monkeypatch.setattr(evidence, "SEARCH_PROVIDER", "tavily")
    tavily_key = evidence.evidence_cache_key(enriched_assertion(), policy, "v1")

    assert exa_key != tavily_key


def test_build_search_requests_groups_same_query_by_domain():
    policy = SimpleNamespace(max_queries_per_domain=2, fallback_to_general_search=True)
    domain_resolution = {
        "preferred_domains": [
            {"domain": "ine.es"},
            {"domain": "sepe.es"},
        ]
    }

    requests = evidence.build_search_requests(enriched_assertion(), domain_resolution, policy)

    assert len(requests) == 2
    assert requests[0]["mode"] == "preferred_domains"
    assert set(requests[0]["include_domains"]) == {"ine.es", "sepe.es"}
    assert requests[0]["query"].startswith("El paro en Barcelona bajo en 2024.")
    assert requests[1]["mode"] == "general_fallback"
    assert requests[1]["include_domains"] is None
    assert requests[1]["query"] == requests[0]["query"]


@pytest.mark.asyncio
async def test_search_evidence_logs_final_search_calls(monkeypatch, capsys):
    original_provider = evidence.SEARCH_PROVIDER
    original_api_key = evidence.API_KEY_PROVIDER
    evidence.SEARCH_PROVIDER = "exa"
    evidence.API_KEY_PROVIDER = "fake-key"

    calls = []

    async def fake_search_with_provider(provider_name, query, max_sources, include_domains=None):
        calls.append({"provider": provider_name, "query": query, "include_domains": include_domains})
        return {"results": []}

    monkeypatch.setattr(evidence, "search_with_provider", fake_search_with_provider)
    async def fake_load_profile_bundle(profile_id="default"):
        calls.append({"profile_id": profile_id})
        return {}, "v1"

    monkeypatch.setattr(evidence, "load_profile_bundle", fake_load_profile_bundle)
    monkeypatch.setattr(
        evidence,
        "resolve_domains",
        lambda assertion, profiles, max_domains=None: {
            "selected_profiles": ["p1"],
            "preferred_domains": [{"domain": "ine.es"}, {"domain": "sepe.es"}],
            "fallback_used": False,
            "reason": "test",
        },
    )
    monkeypatch.setattr(evidence, "cache_collection", None)

    req = SimpleNamespace(
        assertion=enriched_assertion(),
        search_policy=SimpleNamespace(
            use_preferred_domains=True,
            preferred_profile_id="custom-profile",
            max_domains=3,
            max_results=3,
            max_queries_per_domain=2,
            fallback_to_general_search=True,
        ),
    )

    try:
        await evidence.search_evidence(req)
    finally:
        evidence.SEARCH_PROVIDER = original_provider
        evidence.API_KEY_PROVIDER = original_api_key

    captured = capsys.readouterr().out
    assert "search_request" in captured
    assert "preferred_profile_id=custom-profile" in captured
    assert "include_domains=['ine.es', 'sepe.es']" in captured or "include_domains=['sepe.es', 'ine.es']" in captured
    assert calls[0] == {"profile_id": "custom-profile"}
    assert len([call for call in calls if "provider" in call]) == 2


@pytest.mark.asyncio
async def test_search_provider_registry_can_switch_to_exa(monkeypatch):
    calls = []

    class FakeExaProvider(search_providers.SearchProvider):
        name = "exa"

        async def search(self, query, max_sources, include_domains=None):
            calls.append((query, max_sources, include_domains))
            return {"results": []}

    monkeypatch.setattr(search_providers, "registry", search_providers.SearchProviderRegistry())
    search_providers.registry.register("exa", FakeExaProvider())

    result = await search_providers.search_with_provider("exa", "foo", 5, include_domains=["one.es"])

    assert result == {"results": []}
    assert calls == [("foo", 5, ["one.es"])]


def test_merge_search_results_keeps_same_domain_results_and_dedupes_urls():
    results_a = [
        {"url": "https://ine.es/doc1", "title": "Doc1", "content": "Text1"},
        {"url": "https://ine.es/doc2", "title": "Doc2", "content": "Text2"},
    ]
    results_b = [
        {"url": "https://sepe.es/doc", "title": "Doc3", "content": "Text3"},
        {"url": "https://ine.es/doc1", "title": "Doc1 duplicate", "content": "Duplicate"},
        {"url": "https://ine.es/doc3", "title": "Doc4", "content": "Text4"},
    ]

    merged = evidence.merge_search_results(results_a, results_b, max_sources=10)

    assert len(merged) == 4
    assert sum(1 for item in merged if "ine.es" in item["url"]) == 3
    assert sum(1 for item in merged if "sepe.es" in item["url"]) == 1
