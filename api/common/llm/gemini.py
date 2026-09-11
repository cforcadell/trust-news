import os

import httpx

from .errors import LLMConfigurationError, LLMProviderError, LLMResponseError
from .models import LLMRequest, LLMResponse, LLMUsage
from .provider import LLMProvider


class GeminiProvider(LLMProvider):
    name = "gemini"

    def _config(self, model: str) -> tuple[str, str]:
        base = os.getenv("GEMINI_API_URL") or os.getenv("API_URL", "")
        key = os.getenv("GEMINI_API_KEY") or os.getenv("API_KEY", "")
        if not base or not key:
            raise LLMConfigurationError("gemini is not configured")
        return f"{base.rstrip('/')}/models/{model}:generateContent", key

    def _payload(self, request: LLMRequest) -> dict:
        generation = {"temperature": request.temperature}
        if request.json_mode or request.response_schema:
            generation["responseMimeType"] = "application/json"
        if request.response_schema:
            generation["responseSchema"] = request.response_schema
        return {"contents": [{"parts": [{"text": request.prompt}]}], "generationConfig": generation}

    def _parse(self, body: dict, request: LLMRequest) -> LLMResponse:
        try:
            content = body["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("Invalid gemini response") from exc
        metadata = body.get("usageMetadata") or {}
        usage = LLMUsage(
            prompt_tokens=metadata.get("promptTokenCount"), completion_tokens=metadata.get("candidatesTokenCount"),
            total_tokens=metadata.get("totalTokenCount"),
        ) if metadata else None
        return LLMResponse(content=content, provider=self.name, model=request.model, usage=usage)

    def complete(self, request: LLMRequest) -> LLMResponse:
        url, key = self._config(request.model)
        try:
            response = httpx.post(url, headers={"x-goog-api-key": key, "Content-Type": "application/json"}, json=self._payload(request), timeout=float(os.getenv("LLM_TIMEOUT", os.getenv("HTTP_TIMEOUT", "60"))))
            response.raise_for_status()
            return self._parse(response.json(), request)
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(self.name, f"HTTP {exc.response.status_code}", status_code=exc.response.status_code) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(self.name, str(exc) or exc.__class__.__name__) from exc

    async def acomplete(self, request: LLMRequest) -> LLMResponse:
        url, key = self._config(request.model)
        try:
            async with httpx.AsyncClient(timeout=float(os.getenv("LLM_TIMEOUT", os.getenv("HTTP_TIMEOUT", "60")))) as client:
                response = await client.post(url, headers={"x-goog-api-key": key, "Content-Type": "application/json"}, json=self._payload(request))
                response.raise_for_status()
                return self._parse(response.json(), request)
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(self.name, f"HTTP {exc.response.status_code}", status_code=exc.response.status_code) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(self.name, str(exc) or exc.__class__.__name__) from exc
