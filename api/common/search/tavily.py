import os
import re
from typing import Any

import httpx

from .errors import SearchConfigurationError, SearchProviderError
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

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        api_key = os.getenv("API_KEY_PROVIDER", "")
        if not api_key:
            raise SearchConfigurationError("API_KEY_PROVIDER is not configured")
        raw_content = os.getenv("SEARCH_INCLUDE_RAW_CONTENT", "true").strip().lower()
        raw_content_value: Any = raw_content not in {"false", "0", "no"} if raw_content in {"true", "1", "yes", "false", "0", "no"} else raw_content
        payload = {
            "api_key": api_key,
            "query": _official_query(request.query, request.external_source_policy),
            "search_depth": os.getenv("SEARCH_DEPTH", "advanced"),
            "include_answer": os.getenv("SEARCH_INCLUDE_ANSWER", "false").lower() == "true",
            "include_raw_content": raw_content_value,
            "max_results": min(request.max_results, int(os.getenv("SEARCH_MAX_RESULTS", "5"))),
        }
        if request.include_domains:
            payload["include_domains"] = request.include_domains
        try:
            async with httpx.AsyncClient(timeout=float(os.getenv("SEARCH_TIMEOUT", "30"))) as client:
                response = await client.post(os.getenv("SEARCH_API_URL", "https://api.tavily.com/search"), json=payload)
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
