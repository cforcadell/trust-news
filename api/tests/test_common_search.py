from pathlib import Path

import pytest

from common.search import SearchProvider, SearchProviderError, SearchResult, search_with_provider
from common.search.errors import SearchConfigurationError
from common.search.factory import get_search_provider
from common.search.normalization import normalize_domain, normalize_url


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
    api = Path(__file__).resolve().parents[1]
    evidence = (api / "evidence-search" / "main.py").read_text()
    router = (api / "source-router" / "app" / "service.py").read_text()
    assert "from common.search import search_with_provider" in evidence
    assert "from common.search import search_with_provider" in router
