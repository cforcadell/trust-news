from abc import ABC, abstractmethod

from .models import SearchRequest, SearchResult


class SearchProvider(ABC):
    name = "base"

    @abstractmethod
    async def search(self, request: SearchRequest) -> list[SearchResult]:
        """Execute one external search and return normalized real results."""
