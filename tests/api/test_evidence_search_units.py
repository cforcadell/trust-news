import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from common.models.evidence_models import EvidenceSearchPolicy, EvidenceSearchRequestV2, EvidenceSearchResponseV2


ROOT = Path(__file__).resolve().parents[2] / "api" / "evidence-search"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MODULE_PATH = ROOT / "main.py"
spec = importlib.util.spec_from_file_location("evidence_search_main", MODULE_PATH)
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


def test_pdf_text_extraction_uses_each_page_and_normalizes_whitespace(monkeypatch):
    from app import document_fetcher

    class Page:
        def __init__(self, text):
            self.text = text

        def extract_text(self):
            return self.text

    class Reader:
        def __init__(self, content):
            assert content.read() == b"pdf bytes"
            self.pages = [Page("  Primera\n página "), Page("Segunda   página")]

    monkeypatch.setattr(document_fetcher, "PdfReader", Reader)
    assert document_fetcher.extract_pdf_text(b"pdf bytes") == "Primera página Segunda página"


@pytest.mark.asyncio
async def test_pdf_content_is_extracted_and_non_pdf_behavior_is_unchanged(monkeypatch):
    from app import document_fetcher

    class Response:
        status_code = 200
        headers = {"content-type": "application/pdf"}
        content = b"pdf bytes"
        text = "not used"

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            return Response()

    monkeypatch.setattr(document_fetcher.httpx, "AsyncClient", lambda **kwargs: Client())
    monkeypatch.setattr(document_fetcher, "extract_pdf_text", lambda content: "Texto del PDF")
    result = await document_fetcher.fetch_main_text("https://example.test/report.pdf")

    assert result.status == "ok"
    assert result.text == "Texto del PDF"
    assert result.content_type == "application/pdf"


@pytest.mark.asyncio
async def test_tls_hostname_mismatch_retries_only_the_verified_www_variant(monkeypatch):
    from app import document_fetcher

    original = "https://statistics.example.test/report.pdf"
    canonical = "https://www.statistics.example.test/report.pdf"

    class Response:
        status_code = 200
        headers = {"content-type": "application/pdf"}
        content = b"pdf bytes"
        text = "not used"
        url = canonical

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            if url == original:
                raise document_fetcher.httpx.ConnectError(
                    "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Hostname mismatch"
                )
            assert url == canonical
            return Response()

    monkeypatch.setattr(document_fetcher.httpx, "AsyncClient", lambda **kwargs: Client())
    monkeypatch.setattr(document_fetcher, "extract_pdf_text", lambda content: "Texto del PDF")
    result = await document_fetcher.fetch_main_text(original)

    assert result.status == "ok"
    assert result.fetched_url == canonical
    assert result.url_normalized is True
    assert result.normalization_reason == "tls_hostname_mismatch_www_variant"
    assert result.attempted_urls == [original, canonical]


@pytest.mark.asyncio
async def test_connect_errors_do_not_try_hostname_variants(monkeypatch):
    from app import document_fetcher

    original = "https://statistics.example.test/report.pdf"
    calls = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            calls.append(url)
            raise document_fetcher.httpx.ConnectError("network unreachable")

    monkeypatch.setattr(document_fetcher.httpx, "AsyncClient", lambda **kwargs: Client())
    result = await document_fetcher.fetch_main_text(original)

    assert result.status == "failed"
    assert result.error == "connect_error"
    assert result.attempted_urls == [original]
    assert calls == [original]


def test_www_hostname_variant_is_strictly_limited_to_safe_https_hostnames():
    from app.document_fetcher import www_hostname_variant

    assert www_hostname_variant("https://example.test/report") == "https://www.example.test/report"
    assert www_hostname_variant("https://www.example.test/report") == "https://example.test/report"
    assert www_hostname_variant("http://example.test/report") is None
    assert www_hostname_variant("https://127.0.0.1/report") is None
    assert www_hostname_variant("https://user@example.test/report") is None
    assert www_hostname_variant("https://example.test:8443/report") is None


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


def test_query_enrichment_does_not_repeat_context_words_in_different_order():
    population = {
        "context": {
            "temporal_context": [{"value": "2025", "origin": "explicit"}],
            "locations": [{"name": "España", "origin": "explicit"}],
        },
        "search_hints": {
            "search_keywords": ["población España 2025 49 millones"],
            "suggested_queries": ["población de España 2025 49 millones"],
        },
    }
    assert evidence.enrich_query_with_context(
        "Alemania inflación 2025 0%", {
            "context": {
                "temporal_context": [{"value": "2025", "origin": "explicit"}],
                "locations": [{"name": "Alemania", "origin": "explicit"}],
            },
            "search_hints": {"search_keywords": ["inflación Alemania 2025 negativa"]},
        },
    ) == "Alemania inflación 2025 0% negativa"
    assert evidence.enrich_query_with_context(
        "población de España 2025 49 millones", population
    ) == "población de España 2025 49 millones"


def test_base_queries_drop_near_duplicate_suggestions():
    population = {
        "context": {
            "temporal_context": [{"value": "2025", "origin": "explicit"}],
            "locations": [{"name": "España", "origin": "explicit"}],
        },
        "search_hints": {
            "search_keywords": ["población España 2025 49 millones"],
            "suggested_queries": [
                "población de España 2025 49 millones",
                "España población 2025 49 millones",
            ],
        },
    }
    assert evidence.base_queries_for_assertion(population) == ["población de España 2025 49 millones"]


def inflation_assertion():
    return {
        **assertion(),
        "text": "Alemania cerró 2025 con una inflación anual negativa, inferior al 0 %.",
        "topic_code": "ECONOMY_MACRO",
        "context": {
            "locations": [{"name": "Alemania", "scope": "COUNTRY", "country_code": "DE",
                           "origin": "explicit", "confidence": 0.9}],
            "entities": [],
            "temporal_context": [{"value": "2025", "type": "YEAR", "origin": "explicit", "confidence": 0.9}],
            "language": "es",
            "jurisdiction": {"scope": "COUNTRY", "country_code": "DE"},
        },
        "search_hints": {
            "search_keywords": ["Alemania 2025 inflación negativa", "inflación 2025 Alemania", "deflación Alemania 2025"],
            "suggested_queries": ["inflación Alemania 2025 fuente oficial", "Alemania inflación 2025"],
        },
    }


def test_query_relaxation_keeps_topic_location_and_year_but_drops_claim_qualifiers(monkeypatch):
    monkeypatch.setattr(evidence, "EVIDENCE_MAX_QUERY_RELAXATION_ATTEMPTS", 3)
    exact = evidence.base_queries_for_assertion(inflation_assertion())
    variants = evidence.relaxed_query_variants(inflation_assertion(), exact)

    assert variants[0]["query"] == "inflación Alemania 2025"
    assert variants[0]["relaxation_level"] == 1
    assert variants[0]["relaxation_reason"] == "INITIAL_QUERY_EMPTY"
    assert {"negativa", "fuente", "oficial"}.issubset(variants[0]["removed_terms"])
    assert variants[1]["query"] == "deflación Alemania 2025"


@pytest.mark.asyncio
async def test_only_official_executes_relaxed_query_after_empty_exact_search(monkeypatch):
    calls = []

    async def fake_search(provider, query, max_results, include_domains=None, external_source_policy="none"):
        calls.append((query, external_source_policy))
        if query == "inflación Alemania 2025":
            return {"results": [{"url": "https://ec.europa.eu/eurostat/inflation", "title": "Eurostat"}]}
        return {"results": []}

    req = EvidenceSearchRequestV2(
        schema_version="evidence-search-request-v2",
        assertion=inflation_assertion(),
        origin_document={"url": "https://publisher.test/story", "domain": "publisher.test"},
        search_policy={"strategy": "EXT_ONLY_OFFICIAL", "max_domains": 3, "max_results": 3,
                       "max_queries": 1, "preferred_sources": []},
    )
    monkeypatch.setattr(evidence, "cache_collection", None)
    monkeypatch.setattr(evidence, "EVIDENCE_FETCH_FULL_TEXT", False)
    monkeypatch.setattr(evidence, "search_with_provider", fake_search)
    response = await evidence.search_evidence(req)

    assert calls[-1] == ("inflación Alemania 2025", "only_official")
    assert all(policy == "only_official" for _, policy in calls)
    assert response["evidences"][0]["domain"] == "ec.europa.eu"
    relaxed = next(item for item in response["queries_executed"] if item["relaxation_level"] == 1)
    assert relaxed["removed_terms"]


@pytest.mark.asyncio
async def test_relaxed_queries_are_not_executed_when_exact_search_has_results(monkeypatch):
    calls = []

    async def fake_search(provider, query, max_results, include_domains=None, external_source_policy="none"):
        calls.append(query)
        return {"results": [{"url": "https://ec.europa.eu/eurostat/inflation", "title": "Eurostat"}]}

    req = EvidenceSearchRequestV2(
        schema_version="evidence-search-request-v2",
        assertion=inflation_assertion(),
        origin_document={"url": "https://publisher.test/story", "domain": "publisher.test"},
        search_policy={"strategy": "EXT_ONLY_OFFICIAL", "max_domains": 3, "max_results": 3,
                       "max_queries": 1, "preferred_sources": []},
    )
    monkeypatch.setattr(evidence, "cache_collection", None)
    monkeypatch.setattr(evidence, "EVIDENCE_FETCH_FULL_TEXT", False)
    monkeypatch.setattr(evidence, "search_with_provider", fake_search)
    await evidence.search_evidence(req)

    assert len(calls) == 1


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
async def test_failed_document_fetch_never_exposes_provider_snippet_as_citable(monkeypatch):
    async def failed_fetch(*args, **kwargs):
        return SimpleNamespace(status="failed", error="http_403", text="", document_length_chars=0)

    monkeypatch.setattr(evidence, "EVIDENCE_FETCH_FULL_TEXT", True)
    monkeypatch.setattr(evidence, "fetch_main_text", failed_fetch)
    results = await evidence.build_evidences_with_optional_contexts(
        assertion(),
        [{"url": "https://ine.es/report", "title": "INE", "content": "Snippet del proveedor"}],
        {"preferred_sources": [preferred_source()]},
        max_results=1,
    )

    assert results[0]["snippet"] == "Snippet del proveedor"
    assert results[0]["contexts"] == []
    assert results[0]["citation_status"] == "unavailable"


@pytest.mark.asyncio
async def test_local_search_retries_without_routed_domains_after_all_fetches_are_unusable(monkeypatch):
    calls = []
    document = " ".join(["La fuente alternativa confirma la estadística de empleo en Barcelona en 2024."] * 8)

    async def fake_search(provider, query, max_results, include_domains=None, external_source_policy="none"):
        calls.append(include_domains)
        if include_domains:
            return {"results": [{"url": "https://ine.es/unreadable", "title": "Original"}]}
        return {"results": [
            {"url": "https://www.ine.es/still-unreadable", "title": "Subdominio excluido"},
            {"url": "https://alternative.example/report", "title": "Alternativa"},
        ]}

    async def fake_fetch(url, **kwargs):
        if "alternative.example" in url:
            return SimpleNamespace(status="ok", error=None, text=document, document_length_chars=len(document))
        return SimpleNamespace(status="empty_text", error=None, text="", document_length_chars=0)

    monkeypatch.setattr(evidence, "cache_collection", None)
    monkeypatch.setattr(evidence, "EVIDENCE_FETCH_FULL_TEXT", True)
    monkeypatch.setattr(evidence, "search_with_provider", fake_search)
    monkeypatch.setattr(evidence, "fetch_main_text", fake_fetch)
    response = await evidence.search_evidence(request("LOCAL", [preferred_source()]))

    assert calls == [["ine.es"], None]
    assert response["domain_resolution"]["fallback_used"] is True
    assert response["domain_resolution"]["fallback_reason"] == "ALL_INITIAL_FETCHES_UNUSABLE"
    assert response["domain_resolution"]["fallback_excluded_domains"] == ["ine.es"]
    assert len(response["queries_executed"]) == 2
    fallback_query = response["queries_executed"][1]
    assert fallback_query["mode"] == "unrestricted_after_all_fetches_unusable"
    assert fallback_query["include_domains"] is None
    assert fallback_query["excluded_domains"] == ["ine.es"]
    assert [item["url"] for item in response["evidences"]] == [
        "https://ine.es/unreadable", "https://alternative.example/report",
    ]
    assert response["evidences"][1]["citation_status"] == "available"
    assert response["evidences"][1]["retrieval_mode"] == "unrestricted_after_all_fetches_unusable"


@pytest.mark.asyncio
async def test_local_search_does_not_fallback_when_a_routed_source_is_citable(monkeypatch):
    calls = []
    document = " ".join(["La estadística oficial de empleo de Barcelona en 2024 está publicada."] * 8)

    async def fake_search(provider, query, max_results, include_domains=None, external_source_policy="none"):
        calls.append(include_domains)
        return {"results": [{"url": "https://ine.es/readable", "title": "Original"}]}

    async def fake_fetch(*args, **kwargs):
        return SimpleNamespace(status="ok", error=None, text=document, document_length_chars=len(document))

    monkeypatch.setattr(evidence, "cache_collection", None)
    monkeypatch.setattr(evidence, "EVIDENCE_FETCH_FULL_TEXT", True)
    monkeypatch.setattr(evidence, "search_with_provider", fake_search)
    monkeypatch.setattr(evidence, "fetch_main_text", fake_fetch)
    response = await evidence.search_evidence(request("LOCAL", [preferred_source()]))

    assert calls == [["ine.es"]]
    assert response["domain_resolution"].get("fallback_used") is None
    assert len(response["queries_executed"]) == 1


@pytest.mark.asyncio
async def test_fetched_document_context_is_citable_and_hashed(monkeypatch):
    document = " ".join([
        "En 2024 el instituto publicó la estadística oficial de empleo en Barcelona."
    ] * 8)

    async def successful_fetch(*args, **kwargs):
        return SimpleNamespace(
            status="ok", error=None, text=document, document_length_chars=len(document),
            content_type="application/pdf", fetched_url="https://www.ine.es/report",
            url_normalized=True, normalization_reason="tls_hostname_mismatch_www_variant",
            attempted_urls=["https://ine.es/report", "https://www.ine.es/report"],
        )

    monkeypatch.setattr(evidence, "EVIDENCE_FETCH_FULL_TEXT", True)
    monkeypatch.setattr(evidence, "fetch_main_text", successful_fetch)
    results = await evidence.build_evidences_with_optional_contexts(
        assertion(),
        [{"url": "https://ine.es/report", "title": "INE", "content": "Snippet"}],
        {"preferred_sources": [preferred_source()]},
        max_results=1,
    )

    context = results[0]["contexts"][0]
    assert results[0]["citation_status"] == "available"
    assert results[0]["fetched_url"] == "https://www.ine.es/report"
    assert results[0]["url_normalized"] is True
    assert results[0]["normalization_reason"] == "tls_hostname_mismatch_www_variant"
    assert results[0]["fetch_attempted_urls"] == ["https://ine.es/report", "https://www.ine.es/report"]
    assert context["citation_eligible"] is True
    assert context["origin"] == "fetched_document"
    assert len(context["text_sha256"]) == 64


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


@pytest.mark.asyncio
async def test_evaluation_cold_bypasses_cache_without_deleting_it(monkeypatch):
    from unittest.mock import AsyncMock
    from starlette.requests import Request
    from common.utils.evidence_bundle import evidence_bundle_hash

    cache = SimpleNamespace(find_one=AsyncMock(return_value={"response": {"evidences": [], "cached": False}}),
                            update_one=AsyncMock())
    search = AsyncMock(return_value={"results": []})
    monkeypatch.setattr(evidence, "cache_collection", cache)
    monkeypatch.setattr(evidence, "search_with_provider", search)
    warm = await evidence.search_evidence(request())
    assert warm["cached"] is True
    assert warm["evidence_bundle_hash"] == evidence_bundle_hash([])
    search.assert_not_called()
    cold_request = Request({"type": "http", "headers": [(b"x-evaluation-cache", b"COLD")]})
    monkeypatch.delenv("EVALUATION_ALLOW_COLD", raising=False)
    with pytest.raises(evidence.HTTPException) as denied:
        await evidence.search_evidence(request(), cold_request)
    assert denied.value.status_code == 403
    monkeypatch.setenv("EVALUATION_ALLOW_COLD", "true")
    response = await evidence.search_evidence(request(), cold_request)
    assert response["cached"] is False
    assert response["evidence_bundle_hash"] == evidence_bundle_hash([])
    assert search.await_count > 0
    assert cache.find_one.await_count == 1

@pytest.mark.asyncio
async def test_evaluation_trace_keeps_all_chunks_out_of_shared_cache(monkeypatch):
    from unittest.mock import AsyncMock
    from starlette.requests import Request

    document = ("Barcelona 2024 paro oficial. " * 24) + ("Otra noticia sin relación. " * 24)

    async def fake_fetch(*args, **kwargs):
        return SimpleNamespace(status="ok", error=None, text=document, document_length_chars=len(document))

    async def fake_search(*args, **kwargs):
        return {"results": [{"url": "https://ec.europa.eu/eurostat/report", "title": "Informe"}]}

    cache = SimpleNamespace(find_one=AsyncMock(return_value=None), update_one=AsyncMock())
    monkeypatch.setattr(evidence, "cache_collection", cache)
    monkeypatch.setattr(evidence, "search_with_provider", fake_search)
    monkeypatch.setattr(evidence, "fetch_main_text", fake_fetch)
    monkeypatch.setattr(evidence, "EVIDENCE_FETCH_FULL_TEXT", True)
    monkeypatch.setattr(evidence, "EVIDENCE_CHUNK_SIZE_CHARS", 160)
    monkeypatch.setattr(evidence, "EVIDENCE_CONTEXT_WINDOW_BEFORE", 0)
    monkeypatch.setattr(evidence, "EVIDENCE_CONTEXT_WINDOW_AFTER", 0)
    run_id = "123e4567-e89b-12d3-a456-426614174000"
    http_request = Request({"type": "http", "headers": [(b"x-evaluation-run-id", run_id.encode())]})
    response = await evidence.search_evidence(request("EXT_ONLY_OFFICIAL"), http_request)
    EvidenceSearchResponseV2(**response)
    source = response["evidences"][0]
    chunks = source["evaluation_chunks"]
    assert len(chunks) == source["chunks_total"] > 1
    assert all(chunk["text"] and "lexical_score" in chunk and "boost_components" in chunk for chunk in chunks)
    assert any(chunk["selected"] for chunk in chunks)
    assert any(not chunk["selected"] for chunk in chunks)
    assert all(chunk["context_ids"] for chunk in chunks if chunk["included_in_context"])
    assert response["evaluation_trace"]["query_execution"][0]["status"] == "EXECUTED"
    assert response["evaluation_trace"]["query_execution"][0]["returned_urls"] == ["https://ec.europa.eu/eurostat/report"]
    stored = cache.update_one.call_args.args[1]["$set"]["response"]
    assert "evaluation_chunks" not in stored["evidences"][0]
    assert "evaluation_trace" not in stored


@pytest.mark.asyncio
async def test_evaluation_cache_hit_does_not_claim_queries_or_chunks(monkeypatch):
    from unittest.mock import AsyncMock
    from starlette.requests import Request

    cache = SimpleNamespace(find_one=AsyncMock(return_value={"response": {"evidences": [], "cached": False}}))
    search = AsyncMock()
    monkeypatch.setattr(evidence, "cache_collection", cache)
    monkeypatch.setattr(evidence, "search_with_provider", search)
    http_request = Request({"type": "http", "headers": [(b"x-evaluation-run-id", b"123e4567-e89b-12d3-a456-426614174000")]})
    response = await evidence.search_evidence(request(), http_request)
    assert response["cached"] is True
    assert response["evaluation_trace"]["query_execution"] == []
    assert response["evaluation_trace"]["chunk_detail"] == "NOT_RECORDED_ON_CACHE_HIT"
    search.assert_not_called()
