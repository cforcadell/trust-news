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

    async def fake_completion(provider, request, repair_builder):
        repair_builder('{"assertions":[]}', "invalid schema")
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
    assert "response" not in str(trace)
