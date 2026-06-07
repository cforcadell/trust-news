import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import HTTPException


class SearchProvider:
    name = "base"

    async def search(self, query: str, max_sources: int, include_domains: Optional[List[str]] = None) -> Dict[str, Any]:
        raise NotImplementedError


class TavilySearchProvider(SearchProvider):
    name = "tavily"

    async def search(self, query: str, max_sources: int, include_domains: Optional[List[str]] = None) -> Dict[str, Any]:
        api_key = os.getenv("API_KEY_PROVIDER", "")
        if not api_key:
            raise HTTPException(status_code=500, detail="API_KEY_PROVIDER is not configured")

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

        api_url = os.getenv("SEARCH_API_URL", "https://api.tavily.com/search")
        timeout = float(os.getenv("SEARCH_TIMEOUT", "30"))

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(api_url, json=payload)
            resp.raise_for_status()
            return resp.json()


class ExaSearchProvider(SearchProvider):
    name = "exa"

    async def search(self, query: str, max_sources: int, include_domains: Optional[List[str]] = None) -> Dict[str, Any]:
        api_key = os.getenv("API_KEY_PROVIDER", "")
        if not api_key:
            raise HTTPException(status_code=500, detail="API_KEY_PROVIDER is not configured")

        payload = {
            "query": query,
            "numResults": min(max_sources, int(os.getenv("SEARCH_MAX_RESULTS", "5"))),
        }
        if include_domains:
            payload["includeDomains"] = include_domains

        api_url = os.getenv("SEARCH_API_URL", "https://api.exa.ai/search")
        timeout = float(os.getenv("SEARCH_TIMEOUT", "30"))

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(api_url, json=payload, headers={"x-api-key": api_key})
            resp.raise_for_status()
            data = resp.json()

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
    def __init__(self) -> None:
        self._providers: Dict[str, SearchProvider] = {}

    def register(self, name: str, provider: SearchProvider) -> None:
        self._providers[name.lower()] = provider

    def get(self, name: str) -> SearchProvider:
        key = (name or "tavily").lower()
        if key not in self._providers:
            raise ValueError(f"Unknown search provider: {name}")
        return self._providers[key]


registry = SearchProviderRegistry()
registry.register("tavily", TavilySearchProvider())
registry.register("exa", ExaSearchProvider())


def get_search_provider(name: Optional[str] = None) -> SearchProvider:
    return registry.get(name)


def register_search_provider(name: str, provider: SearchProvider) -> None:
    registry.register(name, provider)


async def search_with_provider(provider_name: Optional[str], query: str, max_sources: int, include_domains: Optional[List[str]] = None) -> Dict[str, Any]:
    provider_name = provider_name or os.getenv("SEARCH_PROVIDER", "tavily")
    provider = get_search_provider(provider_name)
    return await provider.search(query, max_sources, include_domains=include_domains)
