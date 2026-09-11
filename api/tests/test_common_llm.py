import json

import pytest
from pydantic import BaseModel

from common.llm import LLMRequest, LLMResponse, acomplete, parse_structured_json
from common.llm.errors import LLMConfigurationError, LLMProviderError
from common.llm.factory import get_llm_provider
from common.llm.openrouter import OpenAICompatibleProvider
from common.llm.provider import LLMProvider


class Payload(BaseModel):
    value: int


class FlakyProvider(LLMProvider):
    name = "flaky"

    def __init__(self):
        self.calls = 0

    def complete(self, request):
        raise NotImplementedError

    async def acomplete(self, request):
        self.calls += 1
        if self.calls == 1:
            raise LLMProviderError(self.name, "timeout", status_code=503)
        return LLMResponse(content='{"value": 7}', provider=self.name, model=request.model)


class InvalidThenValidProvider(FlakyProvider):
    name = "invalid-then-valid"

    async def acomplete(self, request):
        self.calls += 1
        content = "not-json" if self.calls == 1 else '{"value": 8}'
        return LLMResponse(content=content, provider=self.name, model=request.model)


class WrongShapeThenValidProvider(FlakyProvider):
    name = "wrong-shape-then-valid"

    async def acomplete(self, request):
        self.calls += 1
        content = '[]' if self.calls == 1 else '{"value": 8}'
        return LLMResponse(content=content, provider=self.name, model=request.model)


def test_provider_selection_rejects_unknown_provider():
    with pytest.raises(LLMConfigurationError):
        get_llm_provider("invented")


def test_structured_output_validates_schema():
    assert parse_structured_json("```json\n{\"value\": 4}\n```", Payload) == Payload(value=4)


@pytest.mark.asyncio
async def test_async_retry_policy(monkeypatch):
    import common.llm.factory as factory

    provider = FlakyProvider()
    monkeypatch.setitem(factory._providers, "flaky", provider)
    monkeypatch.setenv("LLM_MAX_RETRIES", "2")
    monkeypatch.setenv("LLM_RETRY_DELAY", "0")
    response = await acomplete("flaky", LLMRequest(prompt="x", model="test"))
    assert json.loads(response.content) == {"value": 7}
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_json_mode_retries_invalid_structured_response(monkeypatch):
    import common.llm.factory as factory

    provider = InvalidThenValidProvider()
    monkeypatch.setitem(factory._providers, provider.name, provider)
    monkeypatch.setenv("LLM_MAX_RETRIES", "2")
    monkeypatch.setenv("LLM_RETRY_DELAY", "0")
    response = await acomplete(provider.name, LLMRequest(prompt="x", model="test", json_mode=True))
    assert parse_structured_json(response.content, Payload) == Payload(value=8)
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_response_model_retries_valid_json_with_wrong_shape(monkeypatch):
    import common.llm.factory as factory

    provider = WrongShapeThenValidProvider()
    monkeypatch.setitem(factory._providers, provider.name, provider)
    monkeypatch.setenv("LLM_MAX_RETRIES", "2")
    monkeypatch.setenv("LLM_RETRY_DELAY", "0")
    response = await acomplete(
        provider.name,
        LLMRequest(
            prompt="x",
            model="test",
            response_schema=Payload.model_json_schema(),
            response_model=Payload,
        ),
    )
    assert parse_structured_json(response.content, Payload) == Payload(value=8)
    assert provider.calls == 2


def test_openrouter_payload_requires_strict_json_schema_support():
    schema = Payload.model_json_schema()
    payload = OpenAICompatibleProvider("openrouter")._payload(
        LLMRequest(prompt="x", model="test", response_schema=schema, response_model=Payload)
    )

    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "Payload", "strict": True, "schema": schema},
    }
    assert payload["provider"] == {"require_parameters": True}


def test_all_llm_consumers_import_common_layer():
    from pathlib import Path

    api = Path(__file__).resolve().parents[1]
    assert "from common.llm import" in (api / "generate-asertions" / "main.py").read_text()
    assert "from common.llm import" in (api / "validate-asertions" / "main.py").read_text()
    assert "from common.llm import" in (api / "source-router" / "app" / "classifier.py").read_text()
