from abc import ABC, abstractmethod

from .models import LLMRequest, LLMResponse


class LLMProvider(ABC):
    name = "base"

    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse:
        pass

    @abstractmethod
    async def acomplete(self, request: LLMRequest) -> LLMResponse:
        pass
