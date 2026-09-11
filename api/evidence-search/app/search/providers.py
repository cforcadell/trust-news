"""Compatibility import; provider infrastructure lives in common.search."""

from common.search import SearchProvider, get_search_provider, register_search_provider, search_with_provider
from common.search.exa import ExaSearchProvider, normalize_exa_result
from common.search.tavily import TavilySearchProvider, normalize_tavily_result

__all__ = [
    "SearchProvider", "TavilySearchProvider", "ExaSearchProvider",
    "get_search_provider", "register_search_provider", "search_with_provider",
    "normalize_exa_result", "normalize_tavily_result",
]
