import importlib
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
        "official statistics data authority demography ES-CT ES"
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
    assert requests[0].response_model is None
    assert "failed schema validation" in requests[1].prompt
    assert "CONTINENTAL" in requests[1].prompt
    assert result[0].authority_level.value == "NATIONAL_PRIMARY"


def test_classifier_rejects_ambiguous_authority_value():
    with pytest.raises(ValueError, match="authority_level"):
        classified(authority="CONTINENTAL")


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
