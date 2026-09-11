import importlib
from datetime import timedelta
from types import SimpleNamespace

import pytest


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
        "category": "SOCIAL", "subcategory": "DEMOGRAPHICS", "claim_type": "official_statistic",
        "location": {"name": "Catalunya", "country_code": "ES", "region_code": "ES-CT"},
        "entities": [], "language": "ca",
    }
    data.update(overrides)
    return models.ResolveRouteRequest(**data)


def classified(domain="idescat.cat", country="ES", region="ES-CT", scope="regional", relevance=0.95, authority="regional_primary", applicable=None):
    return models.SourceClassification(
        domain=domain, source_type="official_statistics", authority_level=authority,
        jurisdiction={"scope": scope, "country_code": country, "region_code": region, "applicable_country_codes": applicable or []},
        claim_type_match="exact", subcategory_match="exact", semantic_relevance=relevance,
        classification_confidence=0.95, reason="official source", provider_score=0.8,
    )


def test_route_signature_is_stable_across_years_and_text():
    first = signatures.build_route_signature(request())
    second = signatures.build_route_signature(request())
    assert signatures.route_key(first) == "official_statistic|DEMOGRAPHICS|ES|ES-CT"
    assert first == second


def test_discovery_query_preserves_claim_type_and_jurisdiction_context():
    signature = signatures.build_route_signature(request())

    assert query_builder.build_discovery_queries(signature, request()) == [
        "official statistics statistical institute SOCIAL DEMOGRAPHICS Catalunya ES-CT ES"
    ]


@pytest.mark.asyncio
async def test_classifier_rejects_invented_domain_and_uses_one_batch_call(monkeypatch):
    calls = []

    async def fake_complete(provider, llm_request):
        calls.append(llm_request)
        return SimpleNamespace(content='{"classifications": ['
            '{"domain":"idescat.cat","source_type":"official_statistics","authority_level":"regional_primary",'
            '"jurisdiction":{"scope":"regional","country_code":"ES","region_code":"ES-CT"},'
            '"claim_type_match":"exact","subcategory_match":"exact","semantic_relevance":0.9,"classification_confidence":0.9},'
            '{"domain":"invented.example","semantic_relevance":1,"classification_confidence":1}'
            ']}')

    monkeypatch.setattr(classifier, "acomplete", fake_complete)
    candidates = [models.CandidateSource(domain="idescat.cat", url="https://idescat.cat/data")]
    result = await classifier.classify_candidates(
        signatures.build_route_signature(request()), request(), candidates,
        SimpleNamespace(llm_provider="openrouter", llm_model="test", llm_temperature=0),
    )
    assert [item.domain for item in result] == ["idescat.cat"]
    assert len(calls) == 1
    assert calls[0].response_model is models.ClassificationBatch
    assert calls[0].response_schema["required"] == ["classifications"]
    assert calls[0].response_schema["additionalProperties"] is False


def test_wrong_jurisdiction_is_not_eligible_even_with_high_semantic_score():
    signature = signatures.build_route_signature(request())
    assert not eligibility.is_eligible(signature, classified("stats.govt.nz", "NZ", None, "national", 1.0, "national_primary"))
    assert eligibility.is_eligible(signature, classified())


def test_ranking_is_deterministic():
    signature = signatures.build_route_signature(request())
    sources = [classified("ine.es", region=None, scope="national", authority="national_primary"), classified()]
    assert ranking.rank_sources(signature, sources, 8) == ranking.rank_sources(signature, list(reversed(sources)), 8)
    assert ranking.rank_sources(signature, sources, 8)[0].domain == "idescat.cat"


class MemoryRepository:
    def __init__(self, route=None):
        self.route = route
        self.saved = []
        self.last_filters = None

    async def get(self, key):
        return self.route

    async def save(self, route):
        self.route = route
        self.saved.append(route)
        return route

    async def list(self, filters, limit=100):
        self.last_filters = filters
        return [self.route] if self.route else []


def settings():
    return SimpleNamespace(
        search_provider="exa", discovery_max_results=12, llm_provider="openrouter", llm_model="test",
        llm_temperature=0, refresh_seconds=3600, max_sources=8, router_version="source-router-hybrid-v1",
    )


@pytest.mark.asyncio
async def test_missing_discovers_classifies_ranks_and_persists_then_fresh_is_free(monkeypatch):
    repo = MemoryRepository()
    router = service_module.SourceRouterService(repo, settings())
    calls = []

    async def fake_search(*args, **kwargs):
        calls.append("search")
        return {"results": [{"url": "https://idescat.cat/data", "title": "Data", "content": "Stats", "score": 0.9}]}

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
    assert len(repo.saved) == 1


@pytest.mark.asyncio
async def test_stale_refresh_and_failure_fallback(monkeypatch):
    now = repository_module.utc_now()
    old_source = models.RoutedSource(**classified().model_dump(), rank=1, routing_score=0.9)
    old = models.RouteDocument(
        route_key="official_statistic|DEMOGRAPHICS|ES|ES-CT",
        route_signature=signatures.build_route_signature(request()), sources=[old_source],
        router_version="v1", discovery_provider="exa", classification_model="test",
        created_at=now - timedelta(days=40), updated_at=now - timedelta(days=40),
        last_refreshed_at=now - timedelta(days=40), refresh_after=now - timedelta(days=1),
    )
    repo = MemoryRepository(old)
    router = service_module.SourceRouterService(repo, settings())

    async def fail(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(service_module, "search_with_provider", fail)
    result = await router.resolve(request())
    assert result.route_state == "STALE"
    assert result.stale_route_used is True
    assert result.sources[0].domain == "idescat.cat"


@pytest.mark.asyncio
async def test_stale_route_executes_discovery_and_batch_refresh(monkeypatch):
    now = repository_module.utc_now()
    old_source = models.RoutedSource(**classified().model_dump(), rank=1, routing_score=0.9)
    old = models.RouteDocument(
        route_key="official_statistic|DEMOGRAPHICS|ES|ES-CT",
        route_signature=signatures.build_route_signature(request()), sources=[old_source],
        router_version="v1", discovery_provider="exa", classification_model="old",
        created_at=now - timedelta(days=40), updated_at=now - timedelta(days=40),
        last_refreshed_at=now - timedelta(days=40), refresh_after=now - timedelta(days=1),
    )
    repo = MemoryRepository(old)
    router = service_module.SourceRouterService(repo, settings())
    calls = []

    async def fake_search(*args, **kwargs):
        calls.append("search")
        return {"results": [{"url": "https://ine.es/data", "score": 0.8}]}

    async def fake_classify(*args, **kwargs):
        calls.append("llm")
        return [classified("ine.es", region=None, scope="national", authority="national_primary")]

    monkeypatch.setattr(service_module, "search_with_provider", fake_search)
    monkeypatch.setattr(service_module, "classify_candidates", fake_classify)
    result = await router.resolve(request())
    assert result.route_state == "STALE" and result.stale_route_used is False
    assert calls == ["search", "llm"]
    assert len(repo.saved) == 1


@pytest.mark.asyncio
async def test_missing_provider_or_llm_failure_has_no_static_fallback(monkeypatch):
    router = service_module.SourceRouterService(MemoryRepository(), settings())

    async def fail(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(service_module, "search_with_provider", fail)
    with pytest.raises(RuntimeError, match="provider down"):
        await router.resolve(request())

    async def search_ok(*args, **kwargs):
        return {"results": [{"url": "https://idescat.cat/data"}]}

    async def llm_fail(*args, **kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(service_module, "search_with_provider", search_ok)
    monkeypatch.setattr(service_module, "classify_candidates", llm_fail)
    with pytest.raises(RuntimeError, match="llm down"):
        await router.resolve(request())


@pytest.mark.asyncio
async def test_get_routes_only_reads_repository():
    now = repository_module.utc_now()
    route = models.RouteDocument(
        route_key="official_statistic|DEMOGRAPHICS|ES|ES-CT",
        route_signature=signatures.build_route_signature(request()), category="SOCIAL",
        sources=[], router_version="v1", discovery_provider="exa", classification_model="test",
        created_at=now, updated_at=now, last_refreshed_at=now, refresh_after=now + timedelta(hours=1),
    )
    repo = MemoryRepository(route)
    source_router = SimpleNamespace(repository=repo)
    listed = await routes_module.list_routes(
        source_router=source_router, route_key=None, claim_type="official_statistic", category=None,
        subcategory="DEMOGRAPHICS", country_code="ES", region_code="ES-CT", entity=None, limit=100,
    )
    exact = await routes_module.get_route(route.route_key, source_router=source_router)
    assert listed[0].route_key == route.route_key and listed[0].route_state == "FRESH"
    assert exact.route_key == route.route_key and exact.route_state == "FRESH"
    assert repo.last_filters == {
        "route_key": None, "route_signature.claim_type": "official_statistic", "category": None,
        "route_signature.subcategory": "DEMOGRAPHICS", "route_signature.country_code": "ES",
        "route_signature.region_code": "ES-CT", "entities": None,
    }


@pytest.mark.parametrize(
    "payload,source,expected",
    [
        ({"location": {"name": "Spain", "country_code": "ES"}}, classified("ine.es", "ES", None, "national", authority="national_primary"), True),
        ({"claim_type": "monetary_policy", "subcategory": "MONETARY_POLICY", "location": {"name": "EU", "country_code": "ES"}}, classified("ecb.europa.eu", None, None, "supranational", authority="supranational_primary", applicable=["ES"]), True),
        ({"claim_type": "public_health", "subcategory": "PUBLIC_HEALTH", "location": {"name": "World"}}, classified("who.int", None, None, "global", authority="global_primary"), True),
        ({"location": {"name": "unknown"}}, classified("ine.es", "ES", None, "national", authority="national_primary"), False),
    ],
)
def test_jurisdiction_scenarios(payload, source, expected):
    signature = signatures.build_route_signature(request(**payload))
    assert eligibility.is_eligible(signature, source) is expected
