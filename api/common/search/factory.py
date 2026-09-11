import asyncio
import os

from .errors import SearchConfigurationError, SearchProviderError
from .exa import ExaSearchProvider
from .models import SearchRequest
from .provider import SearchProvider
from .tavily import TavilySearchProvider


_providers: dict[str, SearchProvider] = {"tavily": TavilySearchProvider(), "exa": ExaSearchProvider()}


def register_search_provider(name: str, provider: SearchProvider) -> None:
    _providers[name.strip().lower()] = provider


def get_search_provider(name: str | None = None) -> SearchProvider:
    key = (name or os.getenv("SEARCH_PROVIDER", "tavily")).strip().lower()
    if key not in _providers:
        raise SearchConfigurationError(f"Unknown search provider: {key}")
    return _providers[key]


async def search_with_provider(
    provider_name: str | None,
    query: str,
    max_sources: int,
    include_domains: list[str] | None = None,
    external_source_policy: str = "none",
) -> dict:
    provider = get_search_provider(provider_name)
    request = SearchRequest(
        query=query, max_results=max_sources, include_domains=include_domains or [],
        external_source_policy=external_source_policy,
    )
    attempts = max(1, int(os.getenv("SEARCH_MAX_RETRIES", "2")))
    delay = max(0.0, float(os.getenv("SEARCH_RETRY_DELAY", "0.25")))
    for attempt in range(1, attempts + 1):
        try:
            results = await provider.search(request)
            return {"results": [item.model_dump(exclude_none=True) for item in results]}
        except SearchConfigurationError:
            raise
        except Exception as exc:
            retryable = not isinstance(exc, SearchProviderError) or exc.status_code in {408, 429, 500, 502, 503, 504}
            if attempt >= attempts or not retryable:
                if isinstance(exc, SearchProviderError):
                    raise
                raise SearchProviderError(provider.name, str(exc) or exc.__class__.__name__) from exc
            await asyncio.sleep(delay * attempt)
    return {"results": []}
