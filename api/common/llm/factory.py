import asyncio
import os
import time
from collections.abc import Callable

from .errors import LLMConfigurationError, LLMProviderError, LLMResponseError
from .gemini import GeminiProvider
from .models import LLMRequest, LLMResponse
from .openrouter import OpenAICompatibleProvider
from .provider import LLMProvider
from .structured_output import parse_structured_json


_providers: dict[str, LLMProvider] = {
    "gemini": GeminiProvider(),
    "openrouter": OpenAICompatibleProvider("openrouter"),
    "mistral": OpenAICompatibleProvider("mistral"),
    "grok": OpenAICompatibleProvider("grok"),
}


def register_llm_provider(name: str, provider: LLMProvider) -> None:
    _providers[name.strip().lower()] = provider


def get_llm_provider(name: str) -> LLMProvider:
    key = str(name or "").strip().lower()
    if key not in _providers:
        raise LLMConfigurationError(f"Unknown LLM provider: {key}")
    return _providers[key]


def _attempts() -> int:
    return max(1, int(os.getenv("LLM_MAX_RETRIES", os.getenv("NUM_REINTENTOS", os.getenv("MAX_RETRIES", "3")))))


def _validate_response(request: LLMRequest, response: LLMResponse) -> None:
    if request.response_model is not None and request.strict_response_validation:
        parse_structured_json(response.content, request.response_model)
    elif request.json_mode or request.response_schema:
        parse_structured_json(response.content)


def parse_response(request: LLMRequest, response: LLMResponse):
    """Parse a response using the same model used to generate its JSON Schema."""
    if request.response_model is None:
        raise LLMConfigurationError("Structured parsing requires response_model")
    return parse_structured_json(response.content, request.response_model)


def complete(provider_name: str, request: LLMRequest) -> LLMResponse:
    provider = get_llm_provider(provider_name)
    delay = max(0.0, float(os.getenv("LLM_RETRY_DELAY", os.getenv("RETRY_DELAY", "1"))))
    for attempt in range(1, _attempts() + 1):
        try:
            response = provider.complete(request)
            _validate_response(request, response)
            return response
        except LLMConfigurationError:
            raise
        except Exception as exc:
            retryable = not isinstance(exc, LLMProviderError) or exc.status_code in {408, 429, 500, 502, 503, 504}
            if attempt >= _attempts() or not retryable:
                raise
            time.sleep(delay * attempt)
    raise LLMProviderError(provider.name, "LLM request failed")


async def acomplete(provider_name: str, request: LLMRequest) -> LLMResponse:
    provider = get_llm_provider(provider_name)
    delay = max(0.0, float(os.getenv("LLM_RETRY_DELAY", os.getenv("RETRY_DELAY", "1"))))
    for attempt in range(1, _attempts() + 1):
        try:
            response = await provider.acomplete(request)
            _validate_response(request, response)
            return response
        except LLMConfigurationError:
            raise
        except Exception as exc:
            retryable = not isinstance(exc, LLMProviderError) or exc.status_code in {408, 429, 500, 502, 503, 504}
            if attempt >= _attempts() or not retryable:
                raise
            await asyncio.sleep(delay * attempt)
    raise LLMProviderError(provider.name, "LLM request failed")


def complete_structured(provider_name: str, request: LLMRequest):
    return parse_response(request, complete(provider_name, request))


async def acomplete_structured(provider_name: str, request: LLMRequest):
    return parse_response(request, await acomplete(provider_name, request))


async def acomplete_structured_with_repair(
    provider_name: str,
    request: LLMRequest,
    repair_prompt_builder: Callable[[str, str], str],
):
    """Parse a structured response and make one guided repair when it is invalid.

    Transport failures and malformed JSON keep the regular retry policy. A JSON
    document that fails the Pydantic contract is different: resending the same
    prompt usually repeats the same error, so the second request includes the
    validation error and the original response for the model to correct.
    """
    unvalidated_request = request.model_copy(
        update={"strict_response_validation": False}
    )
    response = await acomplete(provider_name, unvalidated_request)
    try:
        return parse_response(request, response)
    except LLMResponseError as exc:
        repaired_request = request.model_copy(
            update={"prompt": repair_prompt_builder(response.content, str(exc))}
        )
        repaired_response = await acomplete(
            provider_name,
            repaired_request.model_copy(update={"strict_response_validation": False}),
        )
        return parse_response(repaired_request, repaired_response)
