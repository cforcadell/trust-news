import importlib.util
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from common.models.evidence_models import EvidenceSearchPolicy, EvidenceSearchRequestV2, EvidenceSearchResponseV2


ROOT = Path(__file__).resolve().parents[1] / "evidence-search"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MODULE_PATH = ROOT / "main.py"
spec = importlib.util.spec_from_file_location("evidence_search_main", MODULE_PATH)
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


def assertion():
    return {
        "assertion_id": 1,
        "assertion_index": 0,
        "text": "El paro en Barcelona bajo en 2024.",
        "categoryId": 1,
        "topic_code": "EMPLOYMENT",
        "evidence_kind": "STATISTICAL_DATA",
        "taxonomy_version": "routing-taxonomy-v1",
        "context": {
            "locations": [{"name": "Barcelona", "scope": "REGION", "country_code": "ES", "region_code": "ES-CT", "origin": "explicit", "confidence": 1}],
            "entities": [{"name": "INE", "type": "GOVERNMENT_BODY", "role": "AUTHORITY", "origin": "inferred", "confidence": 0.8}],
            "temporal_context": [{"value": "2024", "type": "YEAR", "origin": "explicit", "confidence": 1}],
            "language": "es",
            "jurisdiction": {"scope": "REGION", "country_code": "ES", "region_code": "ES-CT"},
        },
        "search_hints": {"search_keywords": ["estadistica oficial"], "suggested_queries": []},
        "context_confidence": {"location": 1, "entities": 0.8, "temporal": 1},
    }


def preferred_source():
    return {
        "domain": "ine.es",
        "source_type": "STATISTICAL_OFFICE",
        "authority_level": "NATIONAL_PRIMARY",
        "jurisdictions": [{"scope": "COUNTRY", "country_code": "ES"}],
        "topic_codes": ["EMPLOYMENT"],
        "evidence_kinds": ["STATISTICAL_DATA"],
        "languages": ["es"],
        "route_score": 0.9,
        "rank": 1,
        "reason": "official statistics",
        "profile_version": "source-router-v2",
    }


def request(strategy="EXT_OFFICIAL_FIRST", preferred_sources=None):
    return EvidenceSearchRequestV2(
        schema_version="evidence-search-request-v2",
        assertion=assertion(),
        origin_document={"url": "https://publisher.test/story", "domain": "publisher.test"},
        search_policy={
            "strategy": strategy,
            "max_domains": 3,
            "max_results": 3,
            "max_queries": 2,
            "preferred_sources": preferred_sources or [],
        },
    )


def test_query_context_orders_explicit_before_inferred():
    query = evidence.base_queries_for_assertion(assertion())[0]
    assert query.index("2024") < query.index("INE")
    assert "estadistica oficial" in query


def test_strategy_plans_are_explicit_and_have_no_local_fallback():
    local_policy = EvidenceSearchPolicy(
        strategy="LOCAL", max_queries=2, preferred_sources=[preferred_source()]
    )
    local_resolution = {"preferred_sources": [preferred_source()]}
    local = evidence.build_search_requests(assertion(), local_resolution, local_policy)
    assert [item["mode"] for item in local] == ["local_routed"]
    assert local[0]["include_domains"] == ["ine.es"]

    official_first = evidence.build_search_requests(
        assertion(), evidence.empty_domain_resolution(), EvidenceSearchPolicy(strategy="EXT_OFFICIAL_FIRST")
    )
    assert [item["mode"] for item in official_first] == ["external_official_first", "general_fallback"]

    only_official = evidence.build_search_requests(
        assertion(), evidence.empty_domain_resolution(), EvidenceSearchPolicy(strategy="EXT_ONLY_OFFICIAL")
    )
    assert [item["mode"] for item in only_official] == ["external_only_official"]


def test_policy_rejects_none_and_ambiguous_source_ownership():
    with pytest.raises(ValidationError):
        EvidenceSearchPolicy(strategy="NONE")
    with pytest.raises(ValidationError):
        EvidenceSearchPolicy(strategy="LOCAL")
    with pytest.raises(ValidationError):
        EvidenceSearchPolicy(strategy="EXT_OFFICIAL_FIRST", preferred_sources=[preferred_source()])


def test_evidence_preserves_router_metadata_and_origin_relationship():
    resolution = {"preferred_sources": [preferred_source()]}
    result = evidence.evidence_from_source_v2(
        {"url": "https://ine.es/demo", "title": "INE", "content": "Evidence text"}, 1, resolution,
        {"domain": "publisher.test"},
    )
    assert result["source_type"] == "STATISTICAL_OFFICE"
    assert result["authority_level"] == "NATIONAL_PRIMARY"
    assert result["route_score"] == 0.9
    assert result["relationship_to_origin"] == "INDEPENDENT"

    original = evidence.evidence_from_source_v2(
        {"url": "https://publisher.test/story", "content": "Original"}, 2, {},
        {"url": "https://publisher.test/story", "domain": "publisher.test"},
    )
    assert original["relationship_to_origin"] == "ORIGINAL"


def test_cache_key_normalizes_text_and_partitions_origin_policy_and_profile(monkeypatch):
    policy = EvidenceSearchPolicy(strategy="EXT_OFFICIAL_FIRST")
    assertion_a = {**assertion(), "text": "  El   PARO bajo. "}
    assertion_b = {**assertion(), "text": "el paro bajo."}
    origin = {"domain": "publisher.test", "url": None}
    key_a = evidence.evidence_cache_key(assertion_a, origin, policy, "external-ext_official_first")
    key_b = evidence.evidence_cache_key(assertion_b, origin, policy, "external-ext_official_first")
    other_origin = evidence.evidence_cache_key(assertion_b, {"domain": "other.test"}, policy, "external-ext_official_first")
    assert key_a == key_b
    assert key_a != other_origin
    normalized_url_a = evidence.evidence_cache_key(
        assertion_b, {"url": "https://publisher.test/story", "domain": "publisher.test"},
        policy, "external-ext_official_first",
    )
    normalized_url_b = evidence.evidence_cache_key(
        assertion_b, {"url": "HTTPS://WWW.Publisher.Test/story/", "domain": "www.publisher.test"},
        policy, "external-ext_official_first",
    )
    assert normalized_url_a == normalized_url_b

    monkeypatch.setattr(evidence, "SEARCH_PROVIDER", "exa")
    exa = evidence.evidence_cache_key(assertion(), origin, policy, "v1")
    monkeypatch.setattr(evidence, "SEARCH_PROVIDER", "tavily")
    assert exa != evidence.evidence_cache_key(assertion(), origin, policy, "v1")


def test_request_contract_requires_origin():
    payload = request().model_dump(mode="json")
    del payload["origin_document"]
    with pytest.raises(ValidationError):
        EvidenceSearchRequestV2(**payload)


@pytest.mark.asyncio
async def test_search_endpoint_passes_strategy_to_provider(monkeypatch):
    calls = []

    async def fake_search(provider, query, max_results, include_domains=None, external_source_policy="none"):
        calls.append((include_domains, external_source_policy))
        return {"results": []}

    monkeypatch.setattr(evidence, "SEARCH_PROVIDER", "exa")
    monkeypatch.setattr(evidence, "search_with_provider", fake_search)
    monkeypatch.setattr(evidence, "cache_collection", None)
    response = await evidence.search_evidence(request("EXT_OFFICIAL_FIRST"))
    EvidenceSearchResponseV2(**response)
    assert calls == [(None, "official_first"), (None, "none")]
    assert response["search_policy"]["strategy"] == "EXT_OFFICIAL_FIRST"
    assert response["domain_resolution"]["selected_domains"] == []


@pytest.mark.asyncio
async def test_only_official_filters_provider_results_that_violate_policy(monkeypatch):
    async def fake_search(provider, query, max_results, include_domains=None, external_source_policy="none"):
        return {
            "results": [
                {"url": "https://example.com/article", "title": "Media result"},
                {"url": "https://ec.europa.eu/eurostat/data", "title": "Eurostat"},
            ]
        }

    monkeypatch.setattr(evidence, "SEARCH_PROVIDER", "exa")
    monkeypatch.setattr(evidence, "search_with_provider", fake_search)
    monkeypatch.setattr(evidence, "cache_collection", None)
    response = await evidence.search_evidence(request("EXT_ONLY_OFFICIAL"))
    assert [item["domain"] for item in response["evidences"]] == ["ec.europa.eu"]
    assert response["evidences"][0]["source_type"] == "INTERGOVERNMENTAL_ORGANIZATION"


def test_source_type_heuristics_use_normalized_exact_domain_boundaries():
    assert evidence.source_type_for_domain("www.ine.es") == "STATISTICAL_OFFICE"
    assert evidence.source_type_for_domain("ec.europa.eu") == "INTERGOVERNMENTAL_ORGANIZATION"
    assert evidence.source_type_for_domain("datos.gob.es") == "GOVERNMENT_AGENCY"
    assert evidence.source_type_for_domain("notreuters.com") == "MEDIA"


@pytest.mark.asyncio
async def test_search_endpoint_raises_when_every_provider_call_fails(monkeypatch):
    async def fail(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(evidence, "SEARCH_PROVIDER", "exa")
    monkeypatch.setattr(evidence, "search_with_provider", fail)
    monkeypatch.setattr(evidence, "cache_collection", None)
    with pytest.raises(evidence.HTTPException) as exc_info:
        await evidence.search_evidence(request("EXT_ONLY_OFFICIAL"))
    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["code"] == "EVIDENCE_PROVIDER_FAILED"


def test_evidence_search_does_not_call_source_router():
    source = Path(evidence.__file__).read_text()
    assert "SOURCE_ROUTER_URL" not in source
    assert "/routes/resolve" not in source
