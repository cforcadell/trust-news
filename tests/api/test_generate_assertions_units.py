import importlib.util
from pathlib import Path


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
    assert "COUNTRY -> country_code" in prompt
    assert '"country_code":"ES"' in prompt
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
