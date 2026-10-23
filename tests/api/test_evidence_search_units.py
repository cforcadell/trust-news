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


def test_provider_trace_summary_and_url_lineage_preserve_many_to_many_relationships():
    requests = [
        {"provider_call_id": "exa-1", "status": "EXECUTED",
         "returned_urls": ["https://example.test/report", "https://example.test/other"],
         "result_decisions": [
             {"url": "https://example.test/report", "provider_rank": 1, "decision": "RETAINED"},
             {"url": "https://example.test/other", "provider_rank": 2, "decision": "RETAINED"},
         ]},
        {"provider_call_id": "exa-2", "status": "EXECUTED",
         "returned_urls": ["https://example.test/report"],
         "result_decisions": [
             {"url": "https://example.test/report", "provider_rank": 1, "decision": "DUPLICATE"},
         ]},
        {"provider_call_id": "exa-3", "status": "FAILED", "returned_urls": [], "result_decisions": []},
        {"status": "SKIPPED", "returned_urls": [], "result_decisions": []},
    ]
    evidences = [{"url": "https://example.test/report"}]

    evidence.attach_provider_lineage(evidences, requests)

    assert evidences[0]["provider_call_ids"] == ["exa-1", "exa-2"]
    assert evidences[0]["first_provider_call_id"] == "exa-1"
    assert evidence.provider_trace_summary(requests) == {
        "calls_attempted": 3,
        "calls_succeeded": 2,
        "calls_failed": 1,
        "requests_skipped": 1,
        "urls_returned": 3,
        "unique_urls_returned": 2,
    }


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


def test_pdf_text_extraction_respects_page_budget(monkeypatch):
    from app import document_fetcher

    extracted = []

    class Page:
        def __init__(self, index):
            self.index = index

        def extract_text(self):
            extracted.append(self.index)
            return f"page {self.index}"

    class Reader:
        def __init__(self, content):
            self.pages = [Page(index) for index in range(100)]

    monkeypatch.setattr(document_fetcher, "PdfReader", Reader)
    monkeypatch.setattr(document_fetcher, "PDF_MAX_PAGES", 3)

    assert document_fetcher.extract_pdf_text(b"pdf bytes") == "page 0 page 1 page 2"
    assert extracted == [0, 1, 2]


@pytest.mark.asyncio
async def test_html_article_body_is_extracted_from_same_response_without_retry(monkeypatch):
    from app import document_fetcher

    html = ('<html><body><main></main><script type="application/ld+json">'
            '{"@type":"NewsArticle","articleBody":"' + 'Dato oficial de población. ' * 8 + '"}'
            '</script></body></html>')
    calls = []

    class Response:
        status_code = 200
        headers = {"content-type": "text/html"}
        content = html.encode()
        text = html

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            calls.append(url)
            return Response()

    monkeypatch.setattr(document_fetcher.httpx, "AsyncClient", lambda **kwargs: Client())
    result = await document_fetcher.fetch_main_text("https://example.test/report")

    assert result.status == "ok"
    assert result.text.startswith("Dato oficial de población.")
    assert calls == ["https://example.test/report"]


def test_html_extraction_preserves_official_content_wrapped_in_form_and_header():
    from app import document_fetcher

    eustat_style = """
        <html><body><form id="aspnetForm">
          <table><tr><th>Año</th><th>Cuota renovable</th></tr>
          <tr><td>2023</td><td>25,8</td></tr></table>
        </form></body></html>
    """
    elections_style = """
        <html><body><header><div>Cabecera dañada
          <main role="main"><h1>Resultados oficiales</h1>
            <table><tr><th>Grupo</th><th>Escaños</th></tr>
            <tr><td>PPE</td><td>188</td></tr></table>
          </main>
        </div></header></body></html>
    """

    eustat_text = document_fetcher.extract_main_text(eustat_style)
    elections_text = document_fetcher.extract_main_text(elections_style)

    assert "2023" in eustat_text and "25,8" in eustat_text
    assert "Resultados oficiales" in elections_text
    assert "PPE" in elections_text and "188" in elections_text


@pytest.mark.asyncio
async def test_http_202_empty_body_has_specific_failure_code_without_retry(monkeypatch):
    from app import document_fetcher

    calls = []

    class Response:
        status_code = 202
        headers = {"content-type": "text/html"}
        content = b""
        text = ""

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            calls.append(url)
            return Response()

    monkeypatch.setattr(document_fetcher.httpx, "AsyncClient", lambda **kwargs: Client())
    result = await document_fetcher.fetch_main_text("https://eur-lex.example/report")

    assert result.status == "empty_text"
    assert result.failure_code == "HTTP_202_EMPTY_BODY"
    assert result.http_status == 202
    assert result.response_bytes == 0
    assert calls == ["https://eur-lex.example/report"]


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
async def test_document_format_uses_payload_signature_before_content_type(monkeypatch):
    from app import document_fetcher

    class Response:
        status_code = 200
        headers = {"content-type": "text/html"}
        content = b"%PDF-1.7 binary payload"
        text = "%PDF-1.7 binary payload"

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            return Response()

    monkeypatch.setattr(document_fetcher.httpx, "AsyncClient", lambda **kwargs: Client())
    monkeypatch.setattr(document_fetcher, "extract_pdf_text", lambda content: "Texto PDF recuperado")
    result = await document_fetcher.fetch_main_text("https://example.test/download")

    assert result.status == "ok"
    assert result.detected_format == "PDF"
    assert result.extractor == "pdf"
    assert result.text == "Texto PDF recuperado"


@pytest.mark.asyncio
async def test_pdf_extraction_is_offloaded_from_event_loop(monkeypatch):
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

    offloaded = []

    async def to_thread(function, *args):
        offloaded.append((function, args))
        return "Texto PDF recuperado"

    monkeypatch.setattr(document_fetcher.httpx, "AsyncClient", lambda **kwargs: Client())
    monkeypatch.setattr(document_fetcher.asyncio, "to_thread", to_thread)

    result = await document_fetcher.fetch_main_text("https://example.test/report.pdf")

    assert result.status == "ok"
    assert offloaded == [(document_fetcher.extract_pdf_text, (b"pdf bytes",))]


@pytest.mark.asyncio
async def test_plain_text_payload_is_extractable(monkeypatch):
    from app import document_fetcher

    class Response:
        status_code = 200
        headers = {"content-type": "text/plain; charset=utf-8"}
        content = "Dato oficial\nrecuperado".encode()
        text = "Dato oficial\nrecuperado"
        encoding = "utf-8"

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            return Response()

    monkeypatch.setattr(document_fetcher.httpx, "AsyncClient", lambda **kwargs: Client())
    result = await document_fetcher.fetch_main_text("https://example.test/data.txt")

    assert result.status == "ok"
    assert result.detected_format == "TEXT"
    assert result.text == "Dato oficial recuperado"


@pytest.mark.asyncio
async def test_fetch_failure_exposes_stable_stage_code_and_retryability(monkeypatch):
    from app import document_fetcher

    class Response:
        status_code = 429
        headers = {"content-type": "text/html"}
        content = b"Too many requests"
        text = "Too many requests"

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            return Response()

    monkeypatch.setattr(document_fetcher.httpx, "AsyncClient", lambda **kwargs: Client())
    result = await document_fetcher.fetch_main_text("https://example.test/report")

    assert result.status == "failed"
    assert result.failure_stage == "FETCH"
    assert result.failure_code == "HTTP_RATE_LIMITED"
    assert result.retryable is True
    assert result.http_status == 429


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


def test_candidate_selection_round_robins_domains_and_caps_concentration():
    results = [
        {"url": "https://a.example/1"},
        {"url": "https://a.example/2"},
        {"url": "https://a.example/3"},
        {"url": "https://b.example/1"},
        {"url": "https://c.example/1"},
    ]

    selected = evidence.diversify_search_results(results, max_sources=4, max_per_domain=2)

    assert [item["url"] for item in selected] == [
        "https://a.example/1",
        "https://b.example/1",
        "https://c.example/1",
        "https://a.example/2",
    ]


def test_recent_unusable_url_is_replaced_from_existing_candidate_pool(monkeypatch):
    monkeypatch.setattr(evidence, "_recent_unusable_urls", {})
    results = [
        {"url": "https://a.example/broken"},
        {"url": "https://b.example/good"},
        {"url": "https://c.example/good"},
    ]
    evidence.remember_unusable_urls([{"url": results[0]["url"], "fetch_status": "failed",
                                     "fetch_error": "http_404"}])

    selected = evidence.diversify_search_results(results, max_sources=2)

    assert [item["url"] for item in selected] == [
        "https://b.example/good", "https://c.example/good",
    ]
    assert len(selected) == 2
    assert evidence.diversify_search_results(results[:1], max_sources=2) == results[:1]
    evidence.remember_unusable_urls([{"url": results[0]["url"], "fetch_status": "ok"}])
    assert evidence.diversify_search_results(results, max_sources=2)[0]["url"] == results[0]["url"]


@pytest.mark.asyncio
async def test_shared_unusable_history_accepts_mongo_naive_utc_dates(monkeypatch):
    broken_url = "https://a.example/broken"

    class Cursor:
        async def to_list(self, length):
            return [{
                "url": broken_url,
                "expires_at": (
                    evidence.utc_now() + evidence.timedelta(minutes=10)
                ).replace(tzinfo=None),
            }]

    class Collection:
        def find(self, *args, **kwargs):
            return Cursor()

    monkeypatch.setattr(evidence, "unusable_url_collection", Collection())
    monkeypatch.setattr(evidence, "_recent_unusable_urls", {})
    results = [{"url": broken_url}, {"url": "https://b.example/usable"}]

    await evidence.hydrate_unusable_url_history(results)

    assert evidence.diversify_search_results(results, max_sources=1) == [results[1]]


@pytest.mark.asyncio
async def test_unusable_fetch_is_replaced_from_same_provider_batch_without_new_search(monkeypatch):
    search_calls = []
    fetch_calls = []
    document = " ".join(["La fuente alternativa confirma el dato oficial de 2024."] * 12)
    results = [
        {"url": "https://a.example/empty", "title": "A"},
        {"url": "https://b.example/empty", "title": "B"},
        {"url": "https://c.example/empty", "title": "C"},
        {"url": "https://d.example/usable", "title": "D"},
    ]

    async def fake_search(*args, **kwargs):
        search_calls.append((args, kwargs))
        return {"results": results}

    async def fake_fetch(url, **kwargs):
        fetch_calls.append(url)
        if url.endswith("/usable"):
            return SimpleNamespace(
                status="ok", error=None, text=document,
                document_length_chars=len(document), attempts=[{"url": url}],
            )
        return SimpleNamespace(
            status="empty_text", error=None, text="", document_length_chars=0,
            failure_stage="EXTRACTION", failure_code="HTML_NO_MAIN_CONTENT",
            retryable=True, attempts=[{"url": url}],
        )

    monkeypatch.setattr(evidence, "cache_collection", None)
    monkeypatch.setattr(evidence, "unusable_url_collection", None)
    monkeypatch.setattr(evidence, "_recent_unusable_urls", {})
    monkeypatch.setattr(evidence, "EVIDENCE_FETCH_FULL_TEXT", True)
    monkeypatch.setattr(evidence, "search_with_provider", fake_search)
    monkeypatch.setattr(evidence, "fetch_main_text", fake_fetch)

    response = await evidence.search_evidence(request("LOCAL", [preferred_source()]))

    assert len(search_calls) == 1
    assert fetch_calls == [item["url"] for item in results]
    assert response["evidences"][-1]["url"] == "https://d.example/usable"
    assert response["evidences"][-1]["citation_status"] == "available"
    assert response["evidences"][-1]["retrieval_mode"] == (
        "existing_provider_candidates_after_unusable_fetch"
    )
    assert response["domain_resolution"]["local_candidate_refill_count"] == 1


def test_negative_cache_ttl_distinguishes_transient_and_permanent_failures(monkeypatch):
    monkeypatch.setattr(evidence, "EVIDENCE_SEARCH_TRANSIENT_FAILURE_TTL_SECONDS", 30)
    monkeypatch.setattr(evidence, "EVIDENCE_SEARCH_UNUSABLE_TTL_SECONDS", 300)

    transient = evidence.response_cache_policy([
        {"citation_status": "unavailable", "failure": {"code": "TIMEOUT", "retryable": True}}
    ])
    permanent = evidence.response_cache_policy([
        {"citation_status": "unavailable", "failure": {"code": "FORMAT_UNSUPPORTED", "retryable": False}}
    ])

    assert transient == {"classification": "TRANSIENT_NEGATIVE", "ttl_seconds": 30}
    assert permanent == {"classification": "UNUSABLE_NEGATIVE", "ttl_seconds": 300}


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
async def test_local_search_refill_preserves_routed_domains_after_unusable_fetch(monkeypatch):
    calls = []
    document = " ".join(["La fuente alternativa confirma la estadística de empleo en Barcelona en 2024."] * 8)

    async def fake_search(provider, query, max_results, include_domains=None, external_source_policy="none"):
        calls.append(include_domains)
        if len(calls) == 1:
            return {"results": [{"url": "https://ine.es/unreadable", "title": "Original"}]}
        return {"results": [{"url": "https://ine.es/alternative", "title": "Alternativa"}]}

    async def fake_fetch(url, **kwargs):
        if url.endswith("/alternative"):
            return SimpleNamespace(status="ok", error=None, text=document, document_length_chars=len(document))
        return SimpleNamespace(status="empty_text", error=None, text="", document_length_chars=0)

    monkeypatch.setattr(evidence, "cache_collection", None)
    monkeypatch.setattr(evidence, "EVIDENCE_FETCH_FULL_TEXT", True)
    monkeypatch.setattr(evidence, "search_with_provider", fake_search)
    monkeypatch.setattr(evidence, "fetch_main_text", fake_fetch)
    response = await evidence.search_evidence(request("LOCAL", [preferred_source()]))

    assert calls == [["ine.es"], ["ine.es"]]
    assert response["domain_resolution"]["fallback_used"] is True
    assert response["domain_resolution"]["fallback_reason"] == "ALL_INITIAL_FETCHES_UNUSABLE"
    assert response["domain_resolution"]["fallback_excluded_domains"] == []
    assert len(response["queries_executed"]) == 2
    fallback_query = response["queries_executed"][1]
    assert fallback_query["mode"] == "local_routed_after_all_fetches_unusable"
    assert fallback_query["include_domains"] == ["ine.es"]
    assert fallback_query["excluded_domains"] == []
    assert [item["url"] for item in response["evidences"]] == [
        "https://ine.es/unreadable", "https://ine.es/alternative",
    ]
    assert response["evidences"][1]["citation_status"] == "available"
    assert response["evidences"][1]["retrieval_mode"] == "local_routed_after_all_fetches_unusable"


@pytest.mark.asyncio
async def test_official_refill_never_relaxes_the_official_only_policy(monkeypatch):
    calls = []
    document = " ".join(["Eurostat publica la estadística oficial solicitada."] * 12)

    async def fake_search(provider, query, max_results, include_domains=None, external_source_policy="none"):
        calls.append(external_source_policy)
        if len(calls) == 1:
            return {"results": [{"url": "https://ec.europa.eu/unreadable", "title": "Inicial"}]}
        return {"results": [
            {"url": "https://example.com/not-official", "title": "No oficial"},
            {"url": "https://ec.europa.eu/alternative", "title": "Alternativa oficial"},
        ]}

    async def fake_fetch(url, **kwargs):
        if url.endswith("/alternative"):
            return SimpleNamespace(status="ok", error=None, text=document, document_length_chars=len(document))
        return SimpleNamespace(status="empty_text", error=None, text="", document_length_chars=0)

    monkeypatch.setattr(evidence, "cache_collection", None)
    monkeypatch.setattr(evidence, "EVIDENCE_FETCH_FULL_TEXT", True)
    monkeypatch.setattr(evidence, "search_with_provider", fake_search)
    monkeypatch.setattr(evidence, "fetch_main_text", fake_fetch)
    response = await evidence.search_evidence(request("EXT_ONLY_OFFICIAL"))

    assert calls == ["only_official", "only_official"]
    assert [item["domain"] for item in response["evidences"]] == ["ec.europa.eu", "ec.europa.eu"]
    assert response["evidences"][1]["citation_status"] == "available"
    assert response["retrieval_summary"]["fallback_rounds"] == 1
    assert response["retrieval_summary"]["stop_reason"] == "TARGET_REACHED"


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
    provider_trace = exc_info.value.detail["provider_trace"]
    assert provider_trace["summary"]["calls_attempted"] == 1
    assert provider_trace["summary"]["calls_failed"] == 1
    assert provider_trace["requests"][0]["provider_call_id"] == "exa-1"


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
    provider_trace = response["provider_trace"]
    assert provider_trace["capture_status"] == "CAPTURED"
    assert provider_trace["summary"] == {
        "calls_attempted": 1,
        "calls_succeeded": 1,
        "calls_failed": 0,
        "requests_skipped": 0,
        "urls_returned": 1,
        "unique_urls_returned": 1,
    }
    provider_call = provider_trace["requests"][0]
    expected_call_id = f"{evidence.SEARCH_PROVIDER or 'provider'}-1"
    assert provider_call["provider_call_id"] == expected_call_id
    assert provider_call["call_sequence"] == 1
    assert provider_call["result_decisions"] == [{
        "url": "https://ec.europa.eu/eurostat/report",
        "provider_rank": 1,
        "decision": "RETAINED",
    }]
    assert provider_call["started_at"]
    assert provider_call["completed_at"]
    assert provider_call["duration_ms"] >= 0
    assert source["provider_call_ids"] == [expected_call_id]
    assert source["first_provider_call_id"] == expected_call_id
    stored = cache.update_one.call_args.args[1]["$set"]["response"]
    assert "evaluation_chunks" not in stored["evidences"][0]
    assert "evaluation_trace" not in stored
    assert stored["provider_trace"]["requests"][0]["provider_call_id"] == expected_call_id


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
    assert response["provider_trace"]["capture_status"] == "NOT_RECORDED_LEGACY_CACHE"
    assert response["provider_trace"]["summary"]["calls_attempted"] == 0
    assert response["provider_trace"]["requests"] == []
    assert response["evaluation_trace"]["query_execution"] == []
    assert response["evaluation_trace"]["chunk_detail"] == "NOT_RECORDED_ON_CACHE_HIT"
    search.assert_not_called()


@pytest.mark.asyncio
async def test_cache_hit_separates_current_calls_from_original_retrieval(monkeypatch):
    from unittest.mock import AsyncMock
    from starlette.requests import Request

    origin_call = {
        "provider_call_id": "exa-1", "call_sequence": 1, "provider": "exa",
        "status": "EXECUTED", "returned_urls": ["https://ec.europa.eu/report"],
        "result_decisions": [{"url": "https://ec.europa.eu/report", "provider_rank": 1,
                              "decision": "RETAINED"}],
    }
    cached_response = {
        "evidences": [{"url": "https://ec.europa.eu/report", "provider_call_ids": ["exa-1"],
                       "first_provider_call_id": "exa-1"}],
        "cached": False,
        "provider_trace": {"provider": "exa", "cache_hit": False, "capture_status": "CAPTURED",
                           "requests": [origin_call], "summary": evidence.provider_trace_summary([origin_call])},
    }
    cache = SimpleNamespace(find_one=AsyncMock(return_value={"response": cached_response}))
    search = AsyncMock()
    monkeypatch.setattr(evidence, "cache_collection", cache)
    monkeypatch.setattr(evidence, "search_with_provider", search)

    response = await evidence.search_evidence(request(), Request({"type": "http", "headers": []}))

    assert response["cached"] is True
    assert response["provider_trace"]["summary"]["calls_attempted"] == 0
    assert response["provider_trace"]["requests"] == []
    assert response["provider_trace"]["cached_origin_requests"] == [origin_call]
    assert response["provider_trace"]["cached_origin_summary"]["calls_attempted"] == 1
    assert response["evidences"][0]["provider_call_ids"] == ["exa-1"]
    search.assert_not_called()
