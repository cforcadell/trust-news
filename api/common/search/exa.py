import os
from typing import Any

import httpx

from .errors import SearchConfigurationError, SearchProviderError
from .limits import effective_max_results
from .models import SearchRequest, SearchResult
from .normalization import normalize_url
from .provider import SearchProvider
from .tavily import _text


def normalize_exa_result(row: dict[str, Any]) -> dict[str, Any]:
    content = _text(row.get("highlights"), row.get("text"), row.get("summary"), row.get("snippet"), row.get("description"))
    raw = _text(row.get("text"))
    result: dict[str, Any] = {
        "url": normalize_url(row.get("url") or row.get("link") or ""),
        "title": _text(row.get("title"), row.get("name")),
        "content": content,
        "score": row.get("score"),
    }
    if raw and raw != content:
        result["raw_content"] = raw
    if row.get("summary"):
        result["summary"] = _text(row["summary"])
    if isinstance(row.get("highlights"), list):
        result["highlights"] = [_text(item) for item in row["highlights"] if _text(item)]
    return result


class ExaSearchProvider(SearchProvider):
    name = "exa"

    def default_mode(self) -> str:
        return "auto"

    def legacy_mode(self, search_type: str) -> str:
        if search_type not in {"lite", "auto"}:
            raise SearchConfigurationError("Exa search mode must be lite or auto")
        return search_type

    def profile_mode(self, profile: str) -> str | None:
        if profile == "primary":
            mode = os.getenv("EXA_PRIMARY_MODE") or os.getenv("EXA_SEARCH_TYPE_PRIMARY") or os.getenv("EXA_SEARCH_TYPE") or "auto"
        elif profile == "fallback":
            mode = os.getenv("EXA_FALLBACK_MODE") or os.getenv("EXA_SEARCH_TYPE_FALLBACK") or None
        else:
            raise SearchConfigurationError(f"Unknown search profile: {profile}")
        if mode and mode not in {"lite", "auto"}:
            raise SearchConfigurationError("Exa search mode must be lite or auto")
        return mode

    def cache_config(self) -> dict:
        return {**super().cache_config(), "primary_mode": self.profile_mode("primary"),
                "fallback_mode": self.profile_mode("fallback"),
                "endpoint": os.getenv("EXA_API_URL") or os.getenv("SEARCH_API_URL", "https://api.exa.ai/search"),
                "include_highlights": os.getenv("EXA_INCLUDE_HIGHLIGHTS", "true"),
                "include_text": os.getenv("EXA_INCLUDE_TEXT", "true")}

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        api_key = os.getenv("EXA_API_KEY") or os.getenv("API_KEY_PROVIDER", "")
        if not api_key:
            raise SearchConfigurationError("API_KEY_PROVIDER is not configured")
        payload: dict[str, Any] = {
            # Exa has a structured official-source category. Keep policy words
            # out of the semantic query so they do not reduce recall.
            "query": request.query,
            "type": request.search_mode or request.search_type or self.profile_mode(request.search_profile),
            "numResults": effective_max_results(request.max_results),
            "contents": {
                "highlights": os.getenv("EXA_INCLUDE_HIGHLIGHTS", "true").lower() == "true",
                "text": os.getenv("EXA_INCLUDE_TEXT", "true").lower() == "true",
            },
        }
        if payload["type"] not in {"lite", "auto"}:
            raise SearchConfigurationError("EXA_SEARCH_TYPE must be lite or auto")
        if request.include_domains:
            payload["includeDomains"] = request.include_domains
        if request.external_source_policy in {"official_first", "only_official"}:
            payload["category"] = "official source"
        try:
            async with httpx.AsyncClient(timeout=float(os.getenv("SEARCH_TIMEOUT", "30"))) as client:
                response = await client.post(os.getenv("EXA_API_URL") or os.getenv("SEARCH_API_URL", "https://api.exa.ai/search"), json=payload, headers={"x-api-key": api_key})
                response.raise_for_status()
                body = response.json()
                rows = body.get("results") or body.get("data") or []
        except httpx.HTTPStatusError as exc:
            raise SearchProviderError(self.name, f"Exa returned HTTP {exc.response.status_code}", status_code=exc.response.status_code) from exc
        except httpx.HTTPError as exc:
            raise SearchProviderError(self.name, str(exc) or exc.__class__.__name__) from exc
        results = []
        for row in rows:
            normalized = normalize_exa_result(row)
            if not normalized["url"]:
                continue
            metadata = {"provider": self.name}
            for key in ("highlights", "summary"):
                if key in normalized:
                    metadata[key] = normalized.pop(key)
            results.append(SearchResult(
                **normalized, provider_metadata=metadata,
            ))
        return results
