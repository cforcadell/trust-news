import importlib
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from common.llm import LLMResponseError


models = importlib.import_module("source-router.app.models")
signatures = importlib.import_module("source-router.app.signatures")
classifier = importlib.import_module("source-router.app.classifier")
eligibility = importlib.import_module("source-router.app.eligibility")
ranking = importlib.import_module("source-router.app.ranking")
query_builder = importlib.import_module("source-router.app.query_builder")
repository_module = importlib.import_module("source-router.app.repository")
service_module = importlib.import_module("source-router.app.service")
routes_module = importlib.import_module("source-router.app.routes.source_routes")


def request(**overrides):
    data = {
        "topic_code": "DEMOGRAPHY",
        "evidence_kind": "STATISTICAL_DATA",
        "jurisdiction": {"scope": "REGION", "country_code": "ES", "region_code": "ES-CT"},
        "language": "ca",
    }
    data.update(overrides)
    return models.ResolveRouteRequest(**data)


def classified(domain="idescat.cat", jurisdiction=None, authority="REGIONAL_PRIMARY", relevance=0.95):
    return models.SourceClassification(
        domain=domain,
        source_type="STATISTICAL_OFFICE",
        authority_level=authority,
        jurisdictions=[jurisdiction or {"scope": "REGION", "country_code": "ES", "region_code": "ES-CT"}],
        topic_codes=["DEMOGRAPHY"],
        evidence_kinds=["STATISTICAL_DATA"],
        languages=["ca", "es"],
        topic_match="EXACT",
        evidence_kind_match="EXACT",
        semantic_relevance=relevance,
        classification_confidence=0.95,
        reason="official source",
        provider_score=0.8,
    )


def profile(source=None, now=None):
    source = source or classified()
    now = now or repository_module.utc_now()
    return models.DomainProfile(
        domain=source.domain,
        source_type=source.source_type,
        authority_level=source.authority_level,
        jurisdictions=source.jurisdictions,
        topic_codes=source.topic_codes,
        evidence_kinds=source.evidence_kinds,
        languages=source.languages,
        classification_confidence=source.classification_confidence,
        reason=source.reason,
        profile_version="source-router-v2",
        classification_model="test",
        created_at=now,
        updated_at=now,
        last_verified_at=now,
    )


def route_document(*sources, stale=False):
    now = repository_module.utc_now()
    signature = signatures.build_route_signature(request())
    return models.RouteDocument(
        route_key=signatures.route_key(signature),
        route_signature=signature,
        candidates=[ranking.route_candidate(signature, source) for source in sources],
        router_version="source-router-v2",
        discovery_provider="exa",
        classification_model="test",
        created_at=now,
        updated_at=now,
        last_refreshed_at=now,
        refresh_after=now - timedelta(seconds=1) if stale else now + timedelta(hours=1),
    )


def test_route_key_contains_only_normalized_stable_dimensions():
    signature = signatures.build_route_signature(request())
    assert signatures.route_key(signature) == "route-v2|routing-taxonomy-v1|DEMOGRAPHY|STATISTICAL_DATA|REGION:ES:ES-CT"
    assert signatures.route_key(signature) == signatures.route_key(signatures.build_route_signature(request(language="es")))


def test_discovery_query_uses_topic_evidence_and_jurisdiction():
    req = request()
    assert query_builder.build_discovery_queries(signatures.build_route_signature(req), req) == [
        "official statistics data authority demography Catalunya Catalu\u00f1a Spain Espanya"
    ]


def test_discovery_query_localizes_country_name_without_changing_route_key():
    req = request(
        topic_code="HEALTH_PUBLIC_HEALTH",
        evidence_kind="GOVERNMENT_RECORD",
        jurisdiction={"scope": "COUNTRY", "country_code": "SE"},
        language="sv",
    )
    signature = signatures.build_route_signature(req)

    assert signatures.route_key(signature) == (
        "route-v2|routing-taxonomy-v1|HEALTH_PUBLIC_HEALTH|GOVERNMENT_RECORD|COUNTRY:SE"
    )
    assert query_builder.build_discovery_queries(signature, req) == [
        "official government record health public health Sweden Sverige"
    ]


@pytest.mark.asyncio
async def test_classifier_rejects_invented_domain_and_uses_schema(monkeypatch):
    async def fake_complete(provider, llm_request):
        return SimpleNamespace(content='{"classifications":[{"domain":"idescat.cat","source_type":"STATISTICAL_OFFICE","authority_level":"REGIONAL_PRIMARY","jurisdictions":[{"scope":"REGION","country_code":"ES","region_code":"ES-CT"}],"topic_codes":["DEMOGRAPHY"],"evidence_kinds":["STATISTICAL_DATA"],"languages":["ca"],"topic_match":"EXACT","evidence_kind_match":"EXACT","semantic_relevance":0.9,"classification_confidence":0.9,"reason":"official"},{"domain":"invented.example","source_type":"UNKNOWN","authority_level":"UNKNOWN"}]}')

    monkeypatch.setattr(classifier, "acomplete", fake_complete)
    candidates = [models.CandidateSource(domain="idescat.cat", url="https://idescat.cat/data")]
    result = await classifier.classify_candidates(
        signatures.build_route_signature(request()), request(), candidates,
        SimpleNamespace(llm_provider="openrouter", llm_model="test", llm_temperature=0),
    )
    assert [item.domain for item in result] == ["idescat.cat"]


@pytest.mark.asyncio
async def test_classifier_normalizes_unambiguous_authority_alias(monkeypatch):
    async def fake_complete(provider, llm_request):
        assert "use NATIONAL_PRIMARY, never NATIONAL" in llm_request.prompt
        return SimpleNamespace(content='{"classifications":[{"domain":"ine.es","source_type":"STATISTICAL_OFFICE","authority_level":"NATIONAL","jurisdictions":[{"scope":"COUNTRY","country_code":"ES"}],"topic_codes":["DEMOGRAPHY"],"evidence_kinds":["STATISTICAL_DATA"],"languages":["es"],"topic_match":"EXACT","evidence_kind_match":"EXACT","semantic_relevance":0.9,"classification_confidence":0.9,"reason":"official"}]}')

    monkeypatch.setattr(classifier, "acomplete", fake_complete)
    result = await classifier.classify_candidates(
        signatures.build_route_signature(request()),
        request(),
        [models.CandidateSource(domain="ine.es", url="https://ine.es/data")],
        SimpleNamespace(llm_provider="openrouter", llm_model="test", llm_temperature=0),
    )
    assert result[0].authority_level.value == "NATIONAL_PRIMARY"


@pytest.mark.asyncio
async def test_classifier_retry_includes_validation_feedback(monkeypatch):
    requests = []

    async def fake_complete(provider, llm_request):
        requests.append(llm_request)
        if len(requests) == 1:
            return SimpleNamespace(content='{"classifications":[{"domain":"ine.es","authority_level":"CONTINENTAL"}]}')
        return SimpleNamespace(content='{"classifications":[{"domain":"ine.es","source_type":"STATISTICAL_OFFICE","authority_level":"NATIONAL_PRIMARY","jurisdictions":[{"scope":"COUNTRY","country_code":"ES"}],"topic_codes":["DEMOGRAPHY"],"evidence_kinds":["STATISTICAL_DATA"],"languages":["es"],"topic_match":"EXACT","evidence_kind_match":"EXACT","semantic_relevance":0.9,"classification_confidence":0.9,"reason":"official"}]}')

    monkeypatch.setattr(classifier, "acomplete", fake_complete)
    result = await classifier.classify_candidates(
        signatures.build_route_signature(request()),
        request(),
        [models.CandidateSource(domain="ine.es", url="https://ine.es/data")],
        SimpleNamespace(llm_provider="openrouter", llm_model="test", llm_temperature=0),
    )
    assert len(requests) == 2
    assert requests[0].response_model is models.ClassificationBatch
    assert requests[0].strict_response_validation is False
    assert requests[0].response_schema == models.ClassificationBatch.model_json_schema()
    assert "failed schema validation" in requests[1].prompt
    assert "CONTINENTAL" in requests[1].prompt
    assert result[0].authority_level.value == "NATIONAL_PRIMARY"


def test_classifier_rejects_ambiguous_authority_value():
    with pytest.raises(ValueError, match="authority_level"):
        classified(authority="CONTINENTAL")


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_failure", [False, True])
async def test_classifier_preserves_valid_domain_when_other_jurisdiction_fails(monkeypatch, retry_failure):
    valid = classified().model_dump(mode="json")
    invalid = classified("bad.example").model_dump(mode="json")
    invalid["jurisdictions"] = [{"scope": "SUPRANATIONAL", "country_code": "ES"}]
    calls = []

    async def complete(provider, llm_request):
        calls.append(llm_request)
        if len(calls) == 2:
            if retry_failure:
                raise LLMResponseError("invalid JSON on retry")
            return SimpleNamespace(content=json.dumps({"classifications": [invalid]}))
        return SimpleNamespace(content=json.dumps({"classifications": [valid, invalid]}))

    monkeypatch.setattr(classifier, "acomplete", complete)
    result = await classifier.classify_candidates(
        signatures.build_route_signature(request()), request(),
        [models.CandidateSource(domain=d, url=f"https://{d}/") for d in ("idescat.cat", "bad.example")], settings(),
    )
    assert [item.domain for item in result] == ["idescat.cat"]
    assert result.failed_domains == ["bad.example"]
    assert len(calls) == 2
    assert "Return corrected classifications only for: bad.example" in calls[1].prompt


def test_jurisdiction_repairs_only_redundant_codes_without_broadening_coverage():
    raw = classified("ine.es", {"scope": "COUNTRY", "country_code": "ES"}).model_dump(mode="json")
    raw["jurisdictions"][0].update(jurisdiction_code="ES", applicable_country_codes=["ES"])
    repaired = classifier.normalize_classification(raw)
    assert models.SourceClassification.model_validate(repaired).jurisdictions[0].routing_key() == "COUNTRY:ES"
    assert raw["jurisdictions"][0]["jurisdiction_code"] == "ES"  # no input mutation
    raw["jurisdictions"][0]["region_code"] = "ES-CT"
    with pytest.raises(ValueError):
        models.SourceClassification.model_validate(classifier.normalize_classification(raw))


@pytest.mark.asyncio
async def test_classifier_retries_missing_candidate_without_losing_first_result(monkeypatch):
    sources = [classified(), classified("ine.es", {"scope": "COUNTRY", "country_code": "ES"})]
    responses = iter(sources)

    async def complete(*args):
        return SimpleNamespace(content=json.dumps({"classifications": [next(responses).model_dump(mode="json")]}))

    monkeypatch.setattr(classifier, "acomplete", complete)
    result = await classifier.classify_candidates(
        signatures.build_route_signature(request()), request(),
        [models.CandidateSource(domain=item.domain, url=f"https://{item.domain}/") for item in sources], settings(),
    )
    assert {item.domain for item in result} == {"idescat.cat", "ine.es"}
    assert result.failed_domains == []


def test_eligibility_requires_route_matches_authority_and_jurisdiction():
    signature = signatures.build_route_signature(request())
    assert eligibility.is_eligible(signature, classified())
    assert not eligibility.is_eligible(signature, classified(jurisdiction={"scope": "COUNTRY", "country_code": "NZ"}))
    no_match = classified()
    no_match.topic_match = "NONE"
    assert not eligibility.is_eligible(signature, no_match)
    wrong_source_type = classified()
    wrong_source_type.source_type = "MEDIA"
    assert not eligibility.is_eligible(signature, wrong_source_type)
    european = classified(
        "ec.europa.eu",
        {"scope": "SUPRANATIONAL", "jurisdiction_code": "EU", "applicable_country_codes": ["ES", "FR"]},
        "SUPRANATIONAL_PRIMARY",
    )
    assert eligibility.is_eligible(signature, european)


def test_ranking_joins_route_candidates_with_domain_profiles():
    signature = signatures.build_route_signature(request())
    regional = classified()
    national = classified("ine.es", {"scope": "COUNTRY", "country_code": "ES"}, "NATIONAL_PRIMARY")
    candidates = [ranking.route_candidate(signature, national), ranking.route_candidate(signature, regional)]
    profiles = {item.domain: profile(item) for item in (regional, national)}
    result = ranking.rank_sources(candidates, profiles, "ca", 8)
    assert [item.domain for item in result] == ["idescat.cat", "ine.es"]
    assert result[0].profile_version == "source-router-v2"


class MemoryRepository:
    def __init__(self, route=None, profiles=None):
        self.route = route
        self.profiles = profiles or {}
        self.saved_routes = []
        self.last_filters = None

    async def get(self, key):
        return self.route

    async def save(self, route):
        self.route = route
        self.saved_routes.append(route)
        return route

    async def get_profiles(self, domains):
        return {domain: self.profiles[domain] for domain in domains if domain in self.profiles}

    async def save_profiles(self, profiles):
        self.profiles.update({item.domain: item for item in profiles})

    async def list(self, filters, limit=100):
        self.last_filters = filters
        return [self.route] if self.route else []


class IndexCollection:
    def __init__(self):
        self.indexes = []

    async def create_index(self, keys, **options):
        self.indexes.append((keys, options))


@pytest.mark.asyncio
async def test_repository_does_not_create_parallel_array_index():
    routes = IndexCollection()
    profiles = IndexCollection()
    repo = repository_module.SourceRouteRepository(routes, profiles)

    await repo.ensure_indexes()

    assert ("topic_codes", {"name": "profile_topic_codes_v1"}) in profiles.indexes
    assert ("evidence_kinds", {"name": "profile_evidence_kinds_v1"}) in profiles.indexes
    assert not any(isinstance(keys, list) and len(keys) > 1 for keys, _ in profiles.indexes)


def settings():
    return SimpleNamespace(
        search_provider="exa", discovery_max_results=12, llm_provider="openrouter", llm_model="test",
        llm_temperature=0, refresh_seconds=3600, max_sources=8, router_version="source-router-v2",
    )


@pytest.mark.asyncio
async def test_missing_route_builds_profiles_and_fresh_route_reuses_them(monkeypatch):
    repo = MemoryRepository()
    router = service_module.SourceRouterService(repo, settings())
    calls = []

    async def fake_search(*args, **kwargs):
        calls.append("search")
        return {"results": [{"url": "https://idescat.cat/data", "score": 0.9}]}

    async def fake_classify(*args, **kwargs):
        calls.append("llm")
        return [classified()]

    monkeypatch.setattr(service_module, "search_with_provider", fake_search)
    monkeypatch.setattr(service_module, "classify_candidates", fake_classify)
    first = await router.resolve(request())
    second = await router.resolve(request())
    assert first.route_state == "MISSING"
    assert second.route_state == "FRESH"
    assert calls == ["search", "llm"]
    assert list(repo.profiles) == ["idescat.cat"]


@pytest.mark.asyncio
async def test_stale_route_is_used_when_refresh_fails(monkeypatch):
    source = classified()
    old = route_document(source, stale=True)
    repo = MemoryRepository(old, {source.domain: profile(source)})
    router = service_module.SourceRouterService(repo, settings())

    async def fail(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(service_module, "search_with_provider", fail)
    result = await router.resolve(request())
    assert result.route_state == "STALE"
    assert result.stale_route_used is True
    assert result.sources[0].domain == "idescat.cat"


@pytest.mark.asyncio
async def test_missing_route_degrades_when_classification_fails(monkeypatch):
    repo = MemoryRepository()
    router = service_module.SourceRouterService(repo, settings())

    async def fake_search(*args, **kwargs):
        return {"results": [{"url": "https://ine.es/data", "score": 0.9}]}

    async def fail_classification(*args, **kwargs):
        raise LLMResponseError("invalid authority_level")

    monkeypatch.setattr(service_module, "search_with_provider", fake_search)
    monkeypatch.setattr(service_module, "classify_candidates", fail_classification)
    result = await router.resolve(request())
    assert result.route_state == "MISSING"
    assert result.sources == []
    assert result.degraded is True
    assert result.diagnostic_code == "CLASSIFICATION_FAILED"
    assert repo.saved_routes == []


@pytest.mark.asyncio
async def test_classification_failure_uses_only_recent_compatible_discovered_profiles(monkeypatch):
    sources = [classified(), classified("old.example"), classified("wrong-country.example", {"scope": "COUNTRY", "country_code": "NZ"}),
               classified("wrong-topic.example"), classified("wrong-kind.example"), classified("media.example"), classified("undiscovered.example")]
    profiles = {item.domain: profile(item) for item in sources}
    profiles["old.example"].last_verified_at -= timedelta(days=40)
    profiles["wrong-topic.example"].topic_codes = []
    profiles["wrong-kind.example"].evidence_kinds = []
    profiles["media.example"].source_type = models.SourceType.MEDIA
    repo = MemoryRepository(profiles=profiles)
    original = profiles["idescat.cat"].model_dump()
    router = service_module.SourceRouterService(repo, settings())

    async def search(*args):
        return {"results": [{"url": f"https://{item.domain}/"} for item in sources[:-1]]}

    async def fail(*args):
        raise LLMResponseError("invalid jurisdiction")

    monkeypatch.setattr(service_module, "search_with_provider", search)
    monkeypatch.setattr(service_module, "classify_candidates", fail)
    result = await router.resolve(request())
    assert [item.domain for item in result.sources] == ["idescat.cat"]
    assert result.degraded and result.diagnostic_code == "PROFILE_FALLBACK"
    assert result.diagnostics.fallback_domains == ["idescat.cat"]
    assert repo.profiles["idescat.cat"].model_dump() == original
    assert repo.route.refresh_after - repo.route.updated_at == timedelta(seconds=300)
    cached = await router.resolve(request())
    assert cached.route_state == "FRESH"
    assert cached.degraded and cached.diagnostic_code == "PROFILE_FALLBACK"


@pytest.mark.asyncio
async def test_partial_classification_preserves_rejection_diagnostics_and_short_cache(monkeypatch):
    repo = MemoryRepository()
    router = service_module.SourceRouterService(repo, settings())
    wrong = classified("wrong.example", {"scope": "COUNTRY", "country_code": "NZ"})

    async def search(*args):
        return {"results": [{"url": f"https://{d}/"} for d in ("idescat.cat", "bad.example", "wrong.example")]}

    async def classify(*args):
        return classifier.ClassificationResults([classified(), wrong], {"bad.example"})

    monkeypatch.setattr(service_module, "search_with_provider", search)
    monkeypatch.setattr(service_module, "classify_candidates", classify)
    result = await router.resolve(request())
    assert [item.domain for item in result.sources] == ["idescat.cat"]
    assert result.diagnostic_code == "CLASSIFICATION_PARTIAL"
    assert result.diagnostics.rejected_domains == ["wrong.example"]
    assert result.diagnostics.failed_domains == ["bad.example"]
    assert repo.route.refresh_after - repo.route.updated_at == timedelta(seconds=300)


@pytest.mark.asyncio
@pytest.mark.parametrize("with_candidates", [False, True])
async def test_no_eligible_sources_are_diagnosed_and_not_cached(monkeypatch, with_candidates):
    repo = MemoryRepository()
    router = service_module.SourceRouterService(repo, settings())

    async def search(*args):
        return {"results": [{"url": "https://wrong.example/"}] if with_candidates else []}

    async def classify(*args):
        return [classified("wrong.example", {"scope": "COUNTRY", "country_code": "NZ"})] if with_candidates else []

    monkeypatch.setattr(service_module, "search_with_provider", search)
    monkeypatch.setattr(service_module, "classify_candidates", classify)
    result = await router.resolve(request())
    assert result.sources == []
    assert result.diagnostic_code == ("NO_ELIGIBLE_SOURCES" if with_candidates else "NO_DISCOVERY_CANDIDATES")
    assert repo.saved_routes == []


@pytest.mark.asyncio
async def test_route_listing_uses_normalized_filters():
    route = route_document(classified())
    repo = MemoryRepository(route)
    source_router = SimpleNamespace(repository=repo)
    listed = await routes_module.list_routes(
        source_router=source_router, route_key=None, topic_code="demography",
        evidence_kind="statistical_data", jurisdiction_key="region:es:es-ct", limit=100,
    )
    assert listed[0].route_key == route.route_key
    assert repo.last_filters == {
        "route_key": None,
        "route_signature.topic_code": "DEMOGRAPHY",
        "route_signature.evidence_kind": "STATISTICAL_DATA",
        "route_signature.jurisdiction_key": "REGION:ES:ES-CT",
    }


@pytest.mark.asyncio
async def test_evaluation_cold_recomputes_a_fresh_route(monkeypatch):
    source = classified()
    repo = MemoryRepository(route_document(source), {source.domain: profile(source)})
    router = service_module.SourceRouterService(repo, settings())
    calls = []

    async def search(*args, **kwargs):
        calls.append("search")
        return {"results": [{"url": "https://idescat.cat/data"}]}

    async def classify(*args, **kwargs):
        calls.append("llm")
        return [classified()]

    monkeypatch.setattr(service_module, "search_with_provider", search)
    monkeypatch.setattr(service_module, "classify_candidates", classify)
    warm = await router.resolve(request())
    assert warm.route_state == "FRESH"
    assert calls == []
    cold = await router.resolve(request(), force_refresh=True)
    assert cold.route_state == "MISSING"
    assert calls == ["search", "llm"]
    assert cold.sources


@pytest.mark.asyncio
async def test_cold_header_is_gated_and_forwarded_by_http_route(monkeypatch):
    import httpx
    from fastapi import FastAPI
    from unittest.mock import AsyncMock

    app = FastAPI()
    app.include_router(routes_module.router)
    service = SimpleNamespace(resolve=AsyncMock(return_value=models.ResolveRouteResponse(
        route_key="test", route_state="MISSING", sources=[], router_version="test")))
    app.state.source_router_service = service
    monkeypatch.delenv("EVALUATION_ALLOW_COLD", raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal") as client:
        payload = request().model_dump(mode="json")
        response = await client.post("/routes/resolve", json=payload, headers={"X-Evaluation-Cache": "COLD"})
        assert response.status_code == 403
        service.resolve.assert_not_called()
        monkeypatch.setenv("EVALUATION_ALLOW_COLD", "true")
        response = await client.post("/routes/resolve", json=payload, headers={"X-Evaluation-Cache": "COLD"})
        assert response.status_code == 200
        assert service.resolve.call_args.kwargs == {"force_refresh": True}
        response = await client.post("/routes/resolve", json=payload, headers={"X-Evaluation-Run-ID": "invalid"})
        assert response.status_code == 400
        assert service.resolve.await_count == 1

@pytest.mark.asyncio
async def test_evaluation_trace_records_discovery_decisions_rejections_and_score_terms(monkeypatch):
    repo = MemoryRepository()
    router = service_module.SourceRouterService(repo, settings())
    wrong = classified("wrong.example", {"scope": "COUNTRY", "country_code": "NZ"})

    async def search(*args, **kwargs):
        return {"results": [
            {"url": "https://idescat.cat/first", "score": 0.8},
            {"url": "https://idescat.cat/duplicate"},
            {"url": ""},
            {"url": "https://wrong.example/report"},
        ]}

    async def classify(*args, **kwargs):
        return [classified(), wrong]

    monkeypatch.setattr(service_module, "search_with_provider", search)
    monkeypatch.setattr(service_module, "classify_candidates", classify)
    trace = {}
    result = await router.resolve(request(), evaluation_trace=trace)

    assert result.route_state == "MISSING"
    assert [source.domain for source in result.sources] == ["idescat.cat"]
    query = trace["query_execution"][0]
    assert query["status"] == "EXECUTED"
    assert query["provider"] == "exa"
    assert query["returned_urls"][0] == "https://idescat.cat/first"
    assert [item["decision"] for item in query["result_decisions"]] == [
        "RETAINED", "DUPLICATE_DOMAIN", "EMPTY_URL", "RETAINED"]
    assert trace["rejected_domains"] == [{"domain": "wrong.example", "reasons": ["JURISDICTION_MISMATCH"]}]
    good = next(item for item in trace["classification"] if item["domain"] == "idescat.cat")
    assert good["eligible"] is True
    assert abs(sum(good["score_components"].values()) - repo.route.candidates[0].base_score) < 0.00001
    assert good["classification_score"] == repo.route.candidates[0].base_score
    assert trace["ranking"][0]["decision"] == "SELECTED"
    assert trace["ranking"][0]["route_score"] == result.sources[0].route_score

    fresh_trace = {}
    fresh = await router.resolve(request(), evaluation_trace=fresh_trace)
    assert fresh.route_state == "FRESH"
    assert fresh_trace["cache_lookup"] == "FRESH"
    assert fresh_trace["query_execution"] == []
    assert fresh_trace["ranking"][0]["classification_components"] == "NOT_STORED_IN_ROUTE"


@pytest.mark.asyncio
async def test_evaluation_trace_reports_stale_fallback_after_provider_failure(monkeypatch):
    source = classified()
    repo = MemoryRepository(route_document(source, stale=True), {source.domain: profile(source)})
    router = service_module.SourceRouterService(repo, settings())

    async def fail(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(service_module, "search_with_provider", fail)
    trace = {}
    response = await router.resolve(request(), evaluation_trace=trace)
    assert response.route_state == "STALE"
    assert response.stale_route_used is True
    assert trace["cache_lookup"] == "STALE"
    assert trace["query_execution"][0]["status"] == "FAILED"
    assert trace["query_execution"][0]["error_type"] == "RuntimeError"
    assert trace["refresh_error_type"] == "RuntimeError"
    assert trace["diagnostics_origin"] == "stored_route"
    assert trace["ranking"][0]["decision"] == "SELECTED"


@pytest.mark.asyncio
async def test_evaluation_http_route_exposes_actual_trace_only_with_run_id(monkeypatch):
    import httpx
    from fastapi import FastAPI

    repo = MemoryRepository()
    router_service = service_module.SourceRouterService(repo, settings())

    async def search(*args, **kwargs):
        return {"results": [{"url": "https://idescat.cat/data"}]}

    async def classify(*args, **kwargs):
        return [classified()]

    monkeypatch.setattr(service_module, "search_with_provider", search)
    monkeypatch.setattr(service_module, "classify_candidates", classify)
    app = FastAPI()
    app.include_router(routes_module.router)
    app.state.source_router_service = router_service
    run_id = "123e4567-e89b-12d3-a456-426614174000"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal") as client:
        result = await client.post("/routes/resolve", json=request().model_dump(mode="json"),
                                   headers={"X-Evaluation-Run-ID": run_id})
        assert result.status_code == 200
        trace = result.json()["evaluation_trace"]
        assert trace["execution_detail"] == "CAPTURED"
        assert trace["planned_queries"][0]["executed"] is True
        assert trace["query_execution"][0]["returned_urls"] == ["https://idescat.cat/data"]
        warm = await client.post("/routes/resolve", json=request().model_dump(mode="json"),
                                 headers={"X-Evaluation-Run-ID": run_id})
        assert warm.status_code == 200
        warm_trace = warm.json()["evaluation_trace"]
        assert warm_trace["execution_detail"] == "NOT_EXECUTED_CACHE"
        assert warm_trace["planned_queries"][0]["executed"] is False
        plain = await client.post("/routes/resolve", json=request().model_dump(mode="json"))
        assert plain.status_code == 200
        assert "evaluation_trace" not in plain.json()


@pytest.mark.asyncio
async def test_evaluation_observer_failure_does_not_change_selected_sources(monkeypatch):
    source = classified()
    repo = MemoryRepository(route_document(source), {source.domain: profile(source)})
    router = service_module.SourceRouterService(repo, settings())

    def broken_trace(*args, **kwargs):
        raise RuntimeError("trace renderer failed")

    monkeypatch.setattr(service_module, "ranking_rows", broken_trace)
    trace = {}
    response = await router.resolve(request(), evaluation_trace=trace)
    assert response.route_state == "FRESH"
    assert [item.domain for item in response.sources] == ["idescat.cat"]
    assert trace["trace_error_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_evaluation_trace_explains_rank_limit_and_missing_profile():
    top = classified()
    lower = classified("ine.es", {"scope": "COUNTRY", "country_code": "ES"}, "NATIONAL_PRIMARY")
    missing = classified("missing.example")
    route = route_document(top, lower, missing)
    config = settings()
    config.max_sources = 1
    repo = MemoryRepository(route, {top.domain: profile(top), lower.domain: profile(lower)})
    trace = {}
    result = await service_module.SourceRouterService(repo, config).resolve(request(), evaluation_trace=trace)
    assert result.route_state == "FRESH"
    assert len(result.sources) == 1
    assert sorted(item["decision"] for item in trace["ranking"]) == [
        "PROFILE_MISSING", "RANK_LIMIT", "SELECTED"]
    assert trace["query_execution"] == []


@pytest.mark.asyncio
async def test_evaluation_trace_explains_profile_fallback_candidates(monkeypatch):
    eligible = classified()
    expired = classified("expired.example")
    now = repository_module.utc_now()
    profiles = {item.domain: profile(item, now) for item in (eligible, expired)}
    profiles["expired.example"].last_verified_at -= timedelta(days=40)
    repo = MemoryRepository(profiles=profiles)
    router = service_module.SourceRouterService(repo, settings())

    async def search(*args, **kwargs):
        return {"results": [{"url": f"https://{domain}/"} for domain in
                            ("idescat.cat", "expired.example", "missing.example")]}

    async def fail(*args, **kwargs):
        raise LLMResponseError("classification failed")

    monkeypatch.setattr(service_module, "search_with_provider", search)
    monkeypatch.setattr(service_module, "classify_candidates", fail)
    trace = {}
    result = await router.resolve(request(), evaluation_trace=trace)
    assert result.diagnostic_code == "PROFILE_FALLBACK"
    decisions = {item["domain"]: item for item in trace["profile_fallback_candidates"]}
    assert decisions["idescat.cat"]["decision"] == "REUSED"
    assert "PROFILE_EXPIRED" in decisions["expired.example"]["precheck_reasons"]
    assert "PROFILE_NOT_FOUND" in decisions["missing.example"]["precheck_reasons"]
    assert {item["domain"] for item in trace["unclassified_domains"]} == set(decisions)
