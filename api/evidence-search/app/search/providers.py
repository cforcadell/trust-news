import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import HTTPException


class SearchProvider:
    """Base interface implemented by concrete external search providers."""

    name = "base"

    async def search(self, query: str, max_sources: int, include_domains: Optional[List[str]] = None) -> Dict[str, Any]:
        """Execute a search request and return provider-normalized data."""
        # Concrete providers must implement their own HTTP payload and response mapping.
        raise NotImplementedError


class TavilySearchProvider(SearchProvider):
    """Search provider adapter for the Tavily API."""

    name = "tavily"

    async def search(self, query: str, max_sources: int, include_domains: Optional[List[str]] = None) -> Dict[str, Any]:
        """Call Tavily and return its response using the shared provider contract."""
        # Validate credentials early so the API reports configuration issues clearly.
        api_key = os.getenv("API_KEY_PROVIDER", "")
        if not api_key:
            raise HTTPException(status_code=500, detail="API_KEY_PROVIDER is not configured")

        # Build the Tavily payload from environment-backed tuning options.
        payload = {
            "api_key": api_key,
            "query": query,
            "search_depth": os.getenv("SEARCH_DEPTH", "advanced"),
            "include_answer": os.getenv("SEARCH_INCLUDE_ANSWER", "false").lower() == "true",
            "include_raw_content": os.getenv("SEARCH_INCLUDE_RAW_CONTENT", "true").lower() == "true",
            "max_results": min(max_sources, int(os.getenv("SEARCH_MAX_RESULTS", "5"))),
        }
        if include_domains:
            payload["include_domains"] = include_domains

        # Use configurable endpoint and timeout values for local/prod provider swaps.
        api_url = os.getenv("SEARCH_API_URL", "https://api.tavily.com/search")
        timeout = float(os.getenv("SEARCH_TIMEOUT", "30"))

        # Let httpx raise non-2xx responses so callers can log provider failures.
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(api_url, json=payload)
            resp.raise_for_status()
            return resp.json()


class ExaSearchProvider(SearchProvider):
    """Search provider adapter for the Exa API."""

    name = "exa"

    async def search(self, query: str, max_sources: int, include_domains: Optional[List[str]] = None) -> Dict[str, Any]:
        """Call Exa and adapt its response into the shared provider contract."""
        # Validate credentials early so the API reports configuration issues clearly.
        api_key = os.getenv("API_KEY_PROVIDER", "")
        if not api_key:
            raise HTTPException(status_code=500, detail="API_KEY_PROVIDER is not configured")

        # Build the Exa payload and translate include-domain filters to Exa naming.
        payload = {
            "query": query,
            "numResults": min(max_sources, int(os.getenv("SEARCH_MAX_RESULTS", "5"))),
        }
        if include_domains:
            payload["includeDomains"] = include_domains

        # Use configurable endpoint and timeout values for local/prod provider swaps.
        api_url = os.getenv("SEARCH_API_URL", "https://api.exa.ai/search")
        timeout = float(os.getenv("SEARCH_TIMEOUT", "30"))

        # Execute the request and parse the provider response payload.
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(api_url, json=payload, headers={"x-api-key": api_key})
            resp.raise_for_status()
            data = resp.json()

        # Normalize Exa result field names to url/title/content/score for the service layer.
        results = data.get("results") or data.get("data") or []
        adapted = []
        for item in results:
            adapted.append({
                "url": item.get("url") or item.get("link") or "",
                "title": item.get("title") or item.get("name") or "",
                "content": item.get("snippet") or item.get("text") or item.get("description") or "",
                "score": item.get("score"),
            })
        return {"results": adapted}


class SearchProviderRegistry:
    """Small registry that maps provider names to provider adapter instances."""

    def __init__(self) -> None:
        """Create an empty provider registry."""
        # Providers are stored lower-cased to make environment values case-insensitive.
        self._providers: Dict[str, SearchProvider] = {}

    def register(self, name: str, provider: SearchProvider) -> None:
        """Register or replace a provider implementation by name."""
        # Normalize the key once at registration time.
        self._providers[name.lower()] = provider

    def get(self, name: str) -> SearchProvider:
        """Return a provider implementation, defaulting to Tavily."""
        # Empty provider names use Tavily to preserve the historical default behavior.
        key = (name or "tavily").lower()
        if key not in self._providers:
            raise ValueError(f"Unknown search provider: {name}")
        return self._providers[key]


registry = SearchProviderRegistry()
registry.register("tavily", TavilySearchProvider())
registry.register("exa", ExaSearchProvider())


def get_search_provider(name: Optional[str] = None) -> SearchProvider:
    """Look up a configured search provider adapter."""
    # Keep lookup behind a function so tests can replace registry entries cleanly.
    return registry.get(name)


def register_search_provider(name: str, provider: SearchProvider) -> None:
    """Register a custom provider adapter, primarily for tests or extensions."""
    # Delegate validation and normalization to the registry itself.
    registry.register(name, provider)


async def search_with_provider(provider_name: Optional[str], query: str, max_sources: int, include_domains: Optional[List[str]] = None) -> Dict[str, Any]:
    """Resolve the provider name and execute a search through its adapter."""
    # Environment configuration fills in the provider when callers pass None.
    provider_name = provider_name or os.getenv("SEARCH_PROVIDER", "tavily")
    provider = get_search_provider(provider_name)

    # The resolved adapter owns provider-specific request and response behavior.
    return await provider.search(query, max_sources, include_domains=include_domains)
