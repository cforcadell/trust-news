import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).resolve().parents[2] / "api" / "generate-asertions" / "main.py"
SPEC = importlib.util.spec_from_file_location("generate_assertions_main", MODULE_PATH)
generate = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(generate)


def test_openrouter_uses_the_same_strict_schema_as_other_providers(monkeypatch):
    monkeypatch.setattr(generate, "AI_PROVIDER", "openrouter")

    request = generate.build_assertions_llm_request("noticia", "model")

    assert request.json_mode is True
    assert request.response_schema == generate.get_assertions_schema()
    assert request.response_model is generate.AssertionBatch


def test_native_provider_keeps_json_schema(monkeypatch):
    monkeypatch.setattr(generate, "AI_PROVIDER", "gemini")

    request = generate.build_assertions_llm_request("noticia", "model")

    assert request.json_mode is True
    assert request.response_schema == generate.get_assertions_schema()
    assert request.response_model is generate.AssertionBatch


def test_assertion_schema_enforces_the_configured_maximum():
    assert generate.get_assertions_schema()["properties"]["assertions"]["maxItems"] == generate.MAX_ASSERTIONS


def test_prompt_lists_context_contract_and_iso_region_example():
    prompt = generate.build_assertions_prompt("noticia")

    assert "EntityRole: SUBJECT, OBJECT, SOURCE, AUTHORITY, OTHER, UNKNOWN" in prompt
    assert "TemporalType: DATE, DATE_RANGE, YEAR, PERIOD, OTHER, UNKNOWN" in prompt
    assert "CONTRATO OBLIGATORIO DE JURISDICCIÓN" in prompt
    assert '"country_code":"ES"' in prompt
    assert '"scope":"SUPRANATIONAL"' in prompt
    assert '"jurisdiction_code":"EU"' in prompt
    assert '"scope":"REGION"' in prompt
    assert "ES-CT para Catalunya" in prompt
    assert "COUNTRY no puede contener region_code" in prompt


def test_repair_prompt_contains_validation_error_and_invalid_json():
    repair_prompt = generate.build_assertions_repair_prompt(
        '{"scope":"COUNTRY","country_code":null}',
        "COUNTRY jurisdiction requires country_code",
    )

    assert "COUNTRY jurisdiction requires country_code" in repair_prompt
    assert '{"scope":"COUNTRY","country_code":null}' in repair_prompt
    assert "SOLAMENTE el JSON completo corregido" in repair_prompt
    assert "SUPRANATIONAL" in repair_prompt
    assert "Revisa todas las aserciones" in repair_prompt


def test_validation_summary_identifies_malformed_supranational_assertions_without_content():
    invalid = """{
      "assertions": [{
        "idAssertion": "assertion-1",
        "text": "Sensitive generated assertion",
        "categoryId": 10,
        "topic_code": "POLITICS_GOVERNMENT",
        "evidence_kind": "PUBLIC_STATEMENT",
        "context": {"jurisdiction": {
          "scope": "SUPRANATIONAL",
          "country_code": "ES",
          "region_code": null,
          "jurisdiction_code": "EU",
          "applicable_country_codes": []
        }}
      }]
    }"""

    issues = generate.summarize_assertion_validation(invalid)

    assert issues == [{
        "code": "JURISDICTION_CONTRACT_MISMATCH",
        "assertion_index": 0,
        "assertion_id": "assertion-1",
        "location": "assertions.0.context.jurisdiction",
        "message": "Value error, SUPRANATIONAL jurisdiction requires only jurisdiction_code",
        "jurisdiction_scope": "SUPRANATIONAL",
        "present_jurisdiction_fields": ["country_code", "jurisdiction_code"],
    }]
    assert "Sensitive generated assertion" not in str(issues)


@pytest.mark.asyncio
async def test_evaluation_trace_records_structured_repair_without_response_body(monkeypatch):
    monkeypatch.setattr(generate, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(generate, "GEMINI_MODEL", "example-model")
    monkeypatch.setattr(generate, "build_assertions_llm_request", lambda text, model: object())
    monkeypatch.setattr(generate, "parse_assertions_content", lambda content: ["assertion"])

    async def fake_completion(provider, request, repair_builder, usage_observer=None):
        repair_builder('{"assertions":[]}', "invalid schema")
        if usage_observer:
            usage_observer(SimpleNamespace(usage=SimpleNamespace(model_dump=lambda **kwargs: {
                "prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120})))
        return SimpleNamespace(model_dump=lambda **kwargs: {"assertions": []})

    monkeypatch.setattr(generate, "acomplete_structured_with_repair", fake_completion)
    trace = {}
    result = await generate.extract_assertions_from_text("Texto", trace=trace)
    assert result == ["assertion"]
    assert trace["status"] == "COMPLETED"
    assert trace["structured_attempts"] == 2
    assert trace["repair_used"] is True
    assert trace["assertion_count"] == 1
    assert trace["validation_issues"] == []
    assert trace["usage"] == [{"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}]
    assert trace["request_build_seconds"] >= 0
    assert trace["structured_completion_seconds"] >= 0
    assert trace["parse_seconds"] >= 0
    assert "response" not in str(trace)


def test_kafka_generation_publishes_trace_with_timing_fields(monkeypatch):
    assertion = generate.Assertion.model_validate({
        "idAssertion": "1",
        "text": "España superó los 49 millones de habitantes en 2025.",
        "categoryId": 10,
        "topic_code": "DEMOGRAPHY",
        "evidence_kind": "STATISTICAL_DATA",
        "context": {
            "locations": [], "entities": [], "temporal_context": [], "language": "es",
            "jurisdiction": {"scope": "COUNTRY", "country_code": "ES"},
        },
    })

    async def fake_extract(_text, trace=None):
        assert trace is not None
        trace.update({
            "provider": "openrouter", "model": "test-model", "temperature": 0.0,
            "config_version": 1, "structured_attempts": 1, "repair_used": False,
            "duration_seconds": 1.5, "request_build_seconds": 0.1,
            "structured_completion_seconds": 1.3, "parse_seconds": 0.01,
            "status": "COMPLETED", "assertion_count": 1, "usage": [],
        })
        return [assertion]

    class Producer:
        def __init__(self):
            self.sent = []

        async def send_and_wait(self, topic, value):
            self.sent.append((topic, value))

    monkeypatch.setenv("EVALUATION_CAPTURE_GENERATION", "true")
    monkeypatch.setattr(generate, "extract_assertions_from_text", fake_extract)
    producer = Producer()
    request = generate.GenerateAssertionsRequest(
        action="generate_assertions", order_id="order-trace",
        payload={"text": "Noticia", "validation_mode": "LIGHT"},
    )

    asyncio.run(generate.process_message_bytes(request.model_dump_json().encode(), producer))

    assert len(producer.sent) == 1
    assert producer.sent[0][0] == generate.OUTPUT_TOPIC
    response = generate.AssertionsGeneratedResponse.model_validate_json(producer.sent[0][1])
    trace = response.payload.evaluation_trace
    assert trace is not None
    assert trace.request_build_seconds == 0.1
    assert trace.structured_completion_seconds == 1.3
    assert trace.parse_seconds == 0.01
