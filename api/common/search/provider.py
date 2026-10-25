import os
from abc import ABC, abstractmethod

from .errors import SearchConfigurationError
from .models import SearchRequest, SearchResult


class SearchProvider(ABC):
    name = "base"

    def profile_mode(self, profile: str) -> str | None:
        """Return the provider's mode for a logical search profile, if supported."""
        return None

    def default_mode(self) -> str | None:
        return None

    def legacy_mode(self, search_type: str) -> str:
        raise SearchConfigurationError(f"Legacy search_type is not supported by {self.name}")

    def cache_config(self) -> dict:
        """Only settings that can change this provider's search results."""
        return {"provider": self.name, "max_results": os.getenv("SEARCH_PROVIDER_MAX_RESULTS", "50")}

    @abstractmethod
    async def search(self, request: SearchRequest) -> list[SearchResult]:
        """Execute one external search and return normalized real results."""
