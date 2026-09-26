from pathlib import Path

import pytest

from common.search import SearchProvider, SearchProviderError, SearchResult, search_with_provider
from common.search.errors import SearchConfigurationError
from common.search.exa import ExaSearchProvider
from common.search.factory import get_search_provider
from common.search.limits import effective_max_results
from common.search.models import SearchRequest
from common.search.normalization import normalize_domain, normalize_url
from common.search.tavily import TavilySearchProvider


class FlakySearch(SearchProvider):
    name = "flaky-search"

    def __init__(self):
        self.calls = 0

    async def search(self, request):
        self.calls += 1
        if self.calls == 1:
            raise SearchProviderError(self.name, "timeout", status_code=503)
        return [SearchResult(url="https://www.idescat.cat/data", title="Data")]


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
    assert "from common.search import search_with_provider" in evidence
    assert "from common.search import search_with_provider" in router
