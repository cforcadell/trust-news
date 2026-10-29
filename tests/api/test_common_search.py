from pathlib import Path

import pytest

from common.search import SearchProvider, SearchProviderError, SearchResult, get_search_plan, search_with_provider
from common.search.errors import SearchConfigurationError
from common.search.exa import ExaSearchProvider, normalize_exa_result
from common.search.factory import get_search_provider
from common.search.limits import effective_max_results
from common.search.models import SearchRequest
from common.search.normalization import normalize_domain, normalize_url
from common.search.tavily import TavilySearchProvider


def test_exa_preserves_full_text_when_search_excerpt_is_identical():
    document = "Official document text " * 12
    normalized = normalize_exa_result({"url": "https://example.org/report", "text": document})
    assert normalized["content"] == normalized["raw_content"]


class FlakySearch(SearchProvider):
    name = "flaky-search"

    def __init__(self):
        self.calls = 0

    async def search(self, request):
        self.calls += 1
        if self.calls == 1:
            raise SearchProviderError(self.name, "timeout", status_code=503)
        return [SearchResult(url="https://www.idescat.cat/data", title="Data")]


@pytest.mark.asyncio
async def test_new_provider_selects_generic_profiles_without_consumer_changes(monkeypatch):
    import common.search.factory as factory

    class ProfiledSearch(SearchProvider):
        name = "profiled-test"

        def __init__(self):
            self.calls = []

        def default_mode(self):
            return "fast"

        def profile_mode(self, profile):
            return {"primary": "fast", "fallback": "deep"}[profile]

        async def search(self, request):
            self.calls.append((request.search_profile, request.search_mode))
            return [SearchResult(url="https://example.org/report")]

    provider = ProfiledSearch()
    monkeypatch.setitem(factory._providers, provider.name, provider)
    plan = get_search_plan(provider.name)
    assert plan["primary_mode"] == "fast"
    assert plan["fallback_mode"] == "deep"
    first = await search_with_provider(provider.name, "statistics", 3)
    second = await search_with_provider(provider.name, "statistics", 3, search_profile="fallback")
    assert provider.calls == [("primary", "fast"), ("fallback", "deep")]
    assert [first["search_mode"], second["search_mode"]] == ["fast", "deep"]


def test_tavily_plan_ignores_exa_modes_and_has_provider_specific_cache(monkeypatch):
    monkeypatch.setenv("EXA_PRIMARY_MODE", "lite")
    monkeypatch.setenv("EXA_FALLBACK_MODE", "auto")
    tavily = get_search_plan("tavily")
    assert tavily["primary_mode"] == "advanced"
    assert tavily["fallback_mode"] is None
    assert tavily["primary_requires_selection"] is False
    before = tavily["cache_config"]
    monkeypatch.setenv("EXA_PRIMARY_MODE", "auto")
    assert get_search_plan("tavily")["cache_config"] == before
    assert get_search_plan("exa")["cache_config"] != before


@pytest.mark.asyncio
async def test_legacy_exa_type_cannot_leak_into_tavily():
    with pytest.raises(SearchConfigurationError):
        await search_with_provider("tavily", "statistics", 2, search_type="lite")


@pytest.mark.asyncio
@pytest.mark.parametrize("provider, module_name, key_name, url_name, expected_url", [
    (ExaSearchProvider(), "common.search.exa", "EXA_API_KEY", "EXA_API_URL", "https://exa.example/search"),
    (TavilySearchProvider(), "common.search.tavily", "TAVILY_API_KEY", "TAVILY_API_URL", "https://tavily.example/search"),
])
async def test_provider_specific_endpoint_and_key_override_legacy(monkeypatch, provider, module_name,
                                                                  key_name, url_name, expected_url):
    import importlib

    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": []}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            captured.update(url=url, kwargs=kwargs)
            return Response()

    module = importlib.import_module(module_name)
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)
    monkeypatch.setenv("API_KEY_PROVIDER", "legacy-key")
    monkeypatch.setenv("SEARCH_API_URL", "https://legacy.example/search")
    monkeypatch.setenv(key_name, "specific-key")
    monkeypatch.setenv(url_name, expected_url)
    await provider.search(SearchRequest(query="data", max_results=2))
    assert captured["url"] == expected_url
    if provider.name == "exa":
        assert captured["kwargs"]["headers"]["x-api-key"] == "specific-key"
    else:
        assert captured["kwargs"]["json"]["api_key"] == "specific-key"


def test_search_provider_selection_and_url_normalization():
    with pytest.raises(SearchConfigurationError):
        get_search_provider("invented")
    assert normalize_domain("https://www.IDESCAT.cat/data") == "idescat.cat"
    assert normalize_url("https://www.IDESCAT.cat/data#x") == "https://idescat.cat/data"


def test_provider_limit_preserves_caller_limit_and_applies_explicit_guardrail(monkeypatch):
    monkeypatch.delenv("SEARCH_PROVIDER_MAX_RESULTS", raising=False)
    assert effective_max_results(12) == 12
    assert effective_max_results(5) == 5

    monkeypatch.setenv("SEARCH_PROVIDER_MAX_RESULTS", "8")
    assert effective_max_results(12) == 8


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "provider", "payload_field"),
    [
        ("common.search.exa", ExaSearchProvider(), "numResults"),
        ("common.search.tavily", TavilySearchProvider(), "max_results"),
    ],
)
async def test_provider_payload_receives_router_discovery_limit(
    monkeypatch, module_name, provider, payload_field,
):
    import importlib

    captured = {}

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"results": []}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, **kwargs):
            captured.update(kwargs["json"])
            return Response()

    module = importlib.import_module(module_name)
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)
    monkeypatch.setenv("API_KEY_PROVIDER", "test-key")
    monkeypatch.delenv("SEARCH_PROVIDER_MAX_RESULTS", raising=False)

    await provider.search(SearchRequest(query="official statistics Sweden", max_results=12))

    assert captured[payload_field] == 12


@pytest.mark.asyncio
async def test_exa_keeps_official_policy_out_of_semantic_query(monkeypatch):
    import common.search.exa as exa

    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": []}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            captured.update(kwargs["json"])
            return Response()

    monkeypatch.setattr(exa.httpx, "AsyncClient", Client)
    monkeypatch.setenv("API_KEY_PROVIDER", "test-key")
    await ExaSearchProvider().search(SearchRequest(
        query="inflación Alemania 2025", max_results=5, external_source_policy="only_official",
    ))

    assert captured["query"] == "inflación Alemania 2025"
    assert captured["category"] == "official source"
    assert captured["type"] == "auto"

    await ExaSearchProvider().search(SearchRequest(
        query="inflación Alemania 2025", max_results=5, search_type="lite",
    ))
    assert captured["type"] == "lite"


@pytest.mark.asyncio
async def test_search_retries_retryable_provider_failure(monkeypatch):
    import common.search.factory as factory

    provider = FlakySearch()
    monkeypatch.setitem(factory._providers, provider.name, provider)
    monkeypatch.setenv("SEARCH_MAX_RETRIES", "2")
    monkeypatch.setenv("SEARCH_RETRY_DELAY", "0")
    response = await search_with_provider(provider.name, "Catalunya population", 5)
    assert response["results"][0]["url"] == "https://www.idescat.cat/data"
    assert provider.calls == 2


def test_search_consumers_use_shared_layer():
    api = Path(__file__).resolve().parents[2] / "api"
    evidence = (api / "evidence-search" / "main.py").read_text()
    router = (api / "source-router" / "app" / "service.py").read_text()
    assert "from common.search import extract_with_provider, get_search_plan, search_with_provider" in evidence
    assert "from common.search import get_search_plan, search_with_provider" in router


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_type,module_name,body,expected_status", [
    (ExaSearchProvider, "common.search.exa", {"results": [{"url": "https://example.org/a", "text": "document"}],
       "statuses": [{"id": "https://example.org/a", "status": "error", "error": {"tag": "blocked"}}]}, "failed"),
    (TavilySearchProvider, "common.search.tavily", {"results": [],
       "failed_results": [{"url": "https://example.org/a", "error": "blocked"}]}, "failed"),
])
async def test_extract_checks_per_url_success_after_http_200(monkeypatch, provider_type, module_name, body, expected_status):
    import importlib

    module = importlib.import_module(module_name)

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return body

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(module.httpx, "AsyncClient", Client)
    monkeypatch.setenv("API_KEY_PROVIDER", "test-key")
    result = await provider_type().extract("https://example.org/a")
    assert result.status == expected_status
    assert result.text == ""


@pytest.mark.asyncio
async def test_exa_live_extract_requires_live_source(monkeypatch):
    import common.search.exa as exa

    payloads = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"requestId": "call-1", "costDollars": {"total": 0.003},
                    "results": [{"url": "https://example.org/a", "text": "document"}],
                    "statuses": [{"id": "https://example.org/a", "status": "success", "source": "cached"}]}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, _url, **kwargs):
            payloads.append(kwargs["json"])
            return Response()

    monkeypatch.setattr(exa.httpx, "AsyncClient", Client)
    monkeypatch.setenv("API_KEY_PROVIDER", "test-key")
    result = await ExaSearchProvider().extract("https://example.org/a", require_live=True)
    assert payloads == [{"urls": ["https://example.org/a"], "text": True, "maxAgeHours": 0}]
    assert result.status == "failed" and result.error == "FRESHNESS_UNPROVEN"
    assert result.cost_usd == 0.003


@pytest.mark.asyncio
async def test_tavily_live_extract_is_unsupported_without_call():
    result = await TavilySearchProvider().extract("https://example.org/a", require_live=True)
    assert result.status == "unsupported"
    assert result.error == "LIVE_FRESHNESS_UNSUPPORTED"
