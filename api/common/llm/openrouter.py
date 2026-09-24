import os
import re
from copy import deepcopy

import httpx

from common.utils.llm_json import extract_chat_content

from .errors import LLMConfigurationError, LLMProviderError, LLMResponseError
from .models import LLMRequest, LLMResponse, LLMUsage
from .provider import LLMProvider


def _strict_openrouter_schema(schema: dict) -> dict:
    """Normalize Pydantic JSON Schema for OpenAI-compatible strict outputs."""
    normalized = deepcopy(schema)

    def visit(node):
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return
        node.pop("default", None)
        all_of = node.pop("allOf", None)
        if isinstance(all_of, list) and len(all_of) == 1 and isinstance(all_of[0], dict):
            # Pydantic wraps referenced fields that carry defaults in a
            # singleton allOf; OpenAI strict schemas reject that keyword.
            referenced = all_of[0]
            node.update({key: value for key, value in referenced.items() if key not in node})
        elif all_of is not None:
            node["allOf"] = all_of
        for value in list(node.values()):
            visit(value)
        properties = node.get("properties")
        if isinstance(properties, dict):
            node["additionalProperties"] = False
            node["required"] = list(properties)

    visit(normalized)
    return normalized


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, name: str):
        self.name = name

    def _config(self) -> tuple[str, str]:
        prefix = self.name.upper()
        api_url = os.getenv(f"{prefix}_API_URL") or os.getenv("API_URL", "")
        api_key = os.getenv(f"{prefix}_API_KEY") or os.getenv("API_KEY", "")
        if not api_url or not api_key:
            raise LLMConfigurationError(f"{self.name} is not configured")
        return api_url, api_key

    def _payload(self, request: LLMRequest) -> dict:
        payload = {"model": request.model, "messages": [{"role": "user", "content": request.prompt}]}
        # OpenRouter's require_parameters applies to every request parameter.
        # Some structured-output models (notably OpenAI reasoning families) do
        # not expose temperature, which otherwise leaves no eligible endpoint.
        if request.temperature is not None and not (self.name == "openrouter" and request.response_schema):
            payload["temperature"] = request.temperature
        if request.response_schema and self.name == "openrouter":
            raw_name = str(request.response_schema.get("title") or "structured_response")
            schema_name = re.sub(r"[^a-zA-Z0-9_-]", "_", raw_name)[:64] or "structured_response"
            strict_schema = _strict_openrouter_schema(request.response_schema)
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": strict_schema,
                },
            }
            # OpenRouter may otherwise route to an endpoint that silently ignores
            # response_format. Require native support for every requested parameter.
            payload["provider"] = {"require_parameters": True}
        elif request.response_schema or (request.json_mode and self.name == "mistral"):
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _parse(self, body: dict, request: LLMRequest) -> LLMResponse:
        try:
            content = extract_chat_content(body)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMResponseError(f"Invalid {self.name} response") from exc
        raw_usage = body.get("usage") or {}
        usage = LLMUsage(
            prompt_tokens=raw_usage.get("prompt_tokens"), completion_tokens=raw_usage.get("completion_tokens"),
            total_tokens=raw_usage.get("total_tokens"),
        ) if raw_usage else None
        return LLMResponse(content=content, provider=self.name, model=request.model, usage=usage)

    @staticmethod
    def _http_error_message(response: httpx.Response) -> str:
        try:
            body = response.json()
            error = (body.get("error") or {}) if isinstance(body, dict) else {}
            detail = error.get("message")
            raw_detail = (error.get("metadata") or {}).get("raw")
            if raw_detail:
                detail = f"{detail}: {str(raw_detail)[:1000]}"
        except (ValueError, TypeError):
            detail = None
        return f"HTTP {response.status_code}: {detail}" if detail else f"HTTP {response.status_code}"

    def complete(self, request: LLMRequest) -> LLMResponse:
        api_url, api_key = self._config()
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if self.name == "openrouter":
            headers.update({"HTTP-Referer": "https://trust-news", "X-Title": "TrustNews"})
        try:
            response = httpx.post(api_url, headers=headers, json=self._payload(request), timeout=float(os.getenv("LLM_TIMEOUT", os.getenv("HTTP_TIMEOUT", "60"))))
            response.raise_for_status()
            return self._parse(response.json(), request)
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(self.name, self._http_error_message(exc.response), status_code=exc.response.status_code) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(self.name, str(exc) or exc.__class__.__name__) from exc

    async def acomplete(self, request: LLMRequest) -> LLMResponse:
        api_url, api_key = self._config()
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if self.name == "openrouter":
            headers.update({"HTTP-Referer": "https://trust-news", "X-Title": "TrustNews"})
        try:
            async with httpx.AsyncClient(timeout=float(os.getenv("LLM_TIMEOUT", os.getenv("HTTP_TIMEOUT", "60")))) as client:
                response = await client.post(api_url, headers=headers, json=self._payload(request))
                response.raise_for_status()
                return self._parse(response.json(), request)
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(self.name, self._http_error_message(exc.response), status_code=exc.response.status_code) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(self.name, str(exc) or exc.__class__.__name__) from exc
