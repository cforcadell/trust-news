import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import HTTPException


def provider_text(value: Any) -> str:
    """Convert provider text fields into a compact string for evidence snippets."""
    # Providers may return text as a string, a list of highlights, or a missing/null value.
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, list):
        return " ".join(provider_text(item) for item in value if provider_text(item)).strip()
    return ""


def first_provider_text(*values: Any) -> str:
    """Return the first non-empty provider text candidate."""
    # Keep provider-specific fallback chains readable in the adapters below.
    for value in values:
        text = provider_text(value)
        if text:
            return text
    return ""


def tavily_include_raw_content_value() -> Any:
    """Parse Tavily raw-content configuration into the API-supported value."""
    # Tavily accepts booleans and string modes such as text/markdown; preserve both forms.
    raw = os.getenv("SEARCH_INCLUDE_RAW_CONTENT", "true").strip().lower()
    if raw in {"true", "1", "yes"}:
        return True
    if raw in {"false", "0", "no"}:
        return False
    return raw


def normalize_tavily_result(item: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one Tavily result into the shared provider result shape."""
    # Tavily documents results[].content as the primary snippet field.
    content = first_provider_text(item.get("content"), item.get("snippet"), item.get("description"), item.get("raw_content"))

    # Preserve raw_content separately so evidence-search can use it for longer excerpts if needed.
    normalized = {
        "url": item.get("url") or item.get("link") or "",
        "title": item.get("title") or item.get("name") or "",
        "content": content,
        "score": item.get("score"),
    }
    raw_content = provider_text(item.get("raw_content"))
    if raw_content:
        normalized["raw_content"] = raw_content
    return normalized


def normalize_exa_result(item: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one Exa result into the shared provider result shape."""
    # Exa content is requested through contents and may arrive as highlights, text, or summary.
    content = first_provider_text(
        item.get("highlights"),
        item.get("text"),
        item.get("summary"),
        item.get("snippet"),
        item.get("description"),
    )

    # Keep full text as raw_content when it is different from the selected snippet/highlights.
    normalized = {
        "url": item.get("url") or item.get("link") or "",
        "title": item.get("title") or item.get("name") or "",
        "content": content,
        "score": item.get("score"),
    }
    raw_content = provider_text(item.get("text"))
    if raw_content and raw_content != content:
        normalized["raw_content"] = raw_content
    highlights = item.get("highlights")
    if isinstance(highlights, list):
        normalized["highlights"] = [provider_text(highlight) for highlight in highlights if provider_text(highlight)]
    summary = provider_text(item.get("summary"))
    if summary:
        normalized["summary"] = summary
    return normalized


class SearchProvider:
    """Base interface implemented by concrete external search providers."""

    name = "base"

    async def search(
        self,
        query: str,
        max_sources: int,
        include_domains: Optional[List[str]] = None,
        external_source_policy: str = "none",
    ) -> Dict[str, Any]:
        """Execute a search request and return provider-normalized data."""
        # Concrete providers must implement their own HTTP payload and response mapping.
        raise NotImplementedError


def query_with_external_source_policy(query: str, external_source_policy: str) -> str:
    """Ask the upstream provider for official-source preference without local domain lists."""
    policy = (external_source_policy or "none").lower()
    if policy == "official_first":
        return f"{query} preferentemente fuente oficial organismo publico government agency regulator official source".strip()
    if policy == "only_official":
        return f"{query} solo fuentes oficiales organismos publicos government agency regulator official source only".strip()
    return query


class TavilySearchProvider(SearchProvider):
    """Search provider adapter for the Tavily API."""

    name = "tavily"

    async def search(
        self,
        query: str,
        max_sources: int,
        include_domains: Optional[List[str]] = None,
        external_source_policy: str = "none",
    ) -> Dict[str, Any]:
        """Call Tavily and return its response using the shared provider contract."""
        # Validate credentials early so the API reports configuration issues clearly.
        api_key = os.getenv("API_KEY_PROVIDER", "")
        if not api_key:
            raise HTTPException(status_code=500, detail="API_KEY_PROVIDER is not configured")

        # Build the Tavily payload from environment-backed tuning options.
        payload = {
            "api_key": api_key,
            "query": query_with_external_source_policy(query, external_source_policy),
            "search_depth": os.getenv("SEARCH_DEPTH", "advanced"),
            "include_answer": os.getenv("SEARCH_INCLUDE_ANSWER", "false").lower() == "true",
            "include_raw_content": tavily_include_raw_content_value(),
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
            data = resp.json()

        # Normalize results so evidence-search receives the same content field as Exa.
        results = data.get("results") or []
        data["results"] = [normalize_tavily_result(item) for item in results]
        return data


class ExaSearchProvider(SearchProvider):
    """Search provider adapter for the Exa API."""

    name = "exa"

    async def search(
        self,
        query: str,
        max_sources: int,
        include_domains: Optional[List[str]] = None,
        external_source_policy: str = "none",
    ) -> Dict[str, Any]:
        """Call Exa and adapt its response into the shared provider contract."""
        # Validate credentials early so the API reports configuration issues clearly.
        api_key = os.getenv("API_KEY_PROVIDER", "")
        if not api_key:
            raise HTTPException(status_code=500, detail="API_KEY_PROVIDER is not configured")

        # Build the Exa payload and translate include-domain filters to Exa naming.
        payload = {
            "query": query_with_external_source_policy(query, external_source_policy),
            "numResults": min(max_sources, int(os.getenv("SEARCH_MAX_RESULTS", "5"))),
            "contents": {
                "highlights": os.getenv("EXA_INCLUDE_HIGHLIGHTS", "true").lower() == "true",
                "text": os.getenv("EXA_INCLUDE_TEXT", "true").lower() == "true",
            },
        }
        if include_domains:
            payload["includeDomains"] = include_domains
        if (external_source_policy or "none").lower() in {"official_first", "only_official"}:
            payload["category"] = "official source"

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
        return {"results": [normalize_exa_result(item) for item in results]}


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


async def search_with_provider(
    provider_name: Optional[str],
    query: str,
    max_sources: int,
    include_domains: Optional[List[str]] = None,
    external_source_policy: str = "none",
) -> Dict[str, Any]:
    """Resolve the provider name and execute a search through its adapter."""
    # Environment configuration fills in the provider when callers pass None.
    provider_name = provider_name or os.getenv("SEARCH_PROVIDER", "tavily")
    provider = get_search_provider(provider_name)

    # The resolved adapter owns provider-specific request and response behavior.
    return await provider.search(
        query,
        max_sources,
        include_domains=include_domains,
        external_source_policy=external_source_policy,
    )
