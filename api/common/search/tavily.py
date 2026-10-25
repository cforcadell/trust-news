import os
import re
from typing import Any

import httpx

from .errors import SearchConfigurationError, SearchProviderError
from .limits import effective_max_results
from .models import SearchRequest, SearchResult
from .normalization import normalize_url
from .provider import SearchProvider


def _text(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            value = " ".join(str(item) for item in value if item)
        if value:
            return re.sub(r"\s+", " ", str(value)).strip()
    return ""


def _official_query(query: str, policy: str) -> str:
    if policy == "official_first":
        return f"{query} preferentemente fuente oficial organismo publico government agency regulator official source"
    if policy == "only_official":
        return f"{query} solo fuentes oficiales organismos publicos government agency regulator official source only"
    return query


def normalize_tavily_result(row: dict[str, Any]) -> dict[str, Any]:
    raw = _text(row.get("raw_content"))
    result = {
        "url": normalize_url(row.get("url") or row.get("link") or ""),
        "title": _text(row.get("title"), row.get("name")),
        "content": _text(row.get("content"), row.get("snippet"), row.get("description"), raw),
        "score": row.get("score"),
    }
    if raw:
        result["raw_content"] = raw
    return result


class TavilySearchProvider(SearchProvider):
    name = "tavily"

    def default_mode(self) -> str:
        return "advanced"

    def profile_mode(self, profile: str) -> str | None:
        if profile == "primary":
            mode = os.getenv("TAVILY_PRIMARY_DEPTH") or os.getenv("SEARCH_DEPTH", "advanced")
        elif profile == "fallback":
            mode = os.getenv("TAVILY_FALLBACK_DEPTH") or None
        else:
            raise SearchConfigurationError(f"Unknown search profile: {profile}")
        if mode and mode not in {"basic", "advanced"}:
            raise SearchConfigurationError("Tavily search depth must be basic or advanced")
        return mode

    def cache_config(self) -> dict:
        return {**super().cache_config(), "primary_mode": self.profile_mode("primary"),
                "fallback_mode": self.profile_mode("fallback"),
                "endpoint": os.getenv("TAVILY_API_URL") or os.getenv("SEARCH_API_URL", "https://api.tavily.com/search"),
                "include_answer": os.getenv("SEARCH_INCLUDE_ANSWER", "false"),
                "include_raw_content": os.getenv("SEARCH_INCLUDE_RAW_CONTENT", "true")}

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        api_key = os.getenv("TAVILY_API_KEY") or os.getenv("API_KEY_PROVIDER", "")
        if not api_key:
            raise SearchConfigurationError("API_KEY_PROVIDER is not configured")
        raw_content = os.getenv("SEARCH_INCLUDE_RAW_CONTENT", "true").strip().lower()
        raw_content_value: Any = raw_content not in {"false", "0", "no"} if raw_content in {"true", "1", "yes", "false", "0", "no"} else raw_content
        payload = {
            "api_key": api_key,
            "query": _official_query(request.query, request.external_source_policy),
            "search_depth": request.search_mode or self.profile_mode(request.search_profile),
            "include_answer": os.getenv("SEARCH_INCLUDE_ANSWER", "false").lower() == "true",
            "include_raw_content": raw_content_value,
            "max_results": effective_max_results(request.max_results),
        }
        if request.include_domains:
            payload["include_domains"] = request.include_domains
        try:
            async with httpx.AsyncClient(timeout=float(os.getenv("SEARCH_TIMEOUT", "30"))) as client:
                response = await client.post(os.getenv("TAVILY_API_URL") or os.getenv("SEARCH_API_URL", "https://api.tavily.com/search"), json=payload)
                response.raise_for_status()
                rows = response.json().get("results") or []
        except httpx.HTTPStatusError as exc:
            raise SearchProviderError(self.name, f"Tavily returned HTTP {exc.response.status_code}", status_code=exc.response.status_code) from exc
        except httpx.HTTPError as exc:
            raise SearchProviderError(self.name, str(exc) or exc.__class__.__name__) from exc
        results = []
        for row in rows:
            normalized = normalize_tavily_result(row)
            if not normalized["url"]:
                continue
            results.append(SearchResult(**normalized, provider_metadata={"provider": self.name}))
        return results
