import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(scope="module")
def validator():
    import os

    root = Path(__file__).resolve().parents[2]
    os.environ.update({
        "ACCOUNT_ADDRESS": "0x0000000000000000000000000000000000000001",
        "CONTRACT_ADDRESS": "0x0000000000000000000000000000000000000002",
        "CONTRACT_ABI_PATH": str(root / "smart-contracts/artifacts/contracts/TrustNews.sol/TrustNews.json"),
        "RPC_URL": "http://127.0.0.1:1",
        "PRIVATE_KEY": "0x" + "1" * 64,
        "VALIDATOR_TYPE": "4",
        "AI_PROVIDER": "none",
    })
    path = root / "api/validate-asertions/main.py"
    spec = importlib.util.spec_from_file_location("source_orchestration_validator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def minimal_payload():
    assertion = SimpleNamespace(
        categoryId=10,
        topic_code=SimpleNamespace(value="DEMOGRAPHY"),
        evidence_kind=SimpleNamespace(value="STATISTICAL_DATA"),
        context=SimpleNamespace(
            entities=[],
            language="ca",
            jurisdiction=SimpleNamespace(model_dump=lambda mode=None: {
                "scope": "REGION", "country_code": "ES", "region_code": "ES-CT",
            }),
        ),
        model_dump=lambda mode=None: {
            "assertion_id": "1", "assertion_index": 0, "text": "Population", "categoryId": 10,
            "topic_code": "DEMOGRAPHY", "evidence_kind": "STATISTICAL_DATA",
            "taxonomy_version": "routing-taxonomy-v1",
            "context": {"locations": [], "entities": [], "temporal_context": [], "language": "ca", "jurisdiction": {"scope": "REGION", "country_code": "ES", "region_code": "ES-CT"}},
            "search_hints": {}, "context_confidence": {},
        },
    )
    origin = SimpleNamespace(model_dump=lambda mode=None: {
        "url": "https://publisher.test/story", "domain": "publisher.test",
    })
    return SimpleNamespace(assertion=assertion, origin_document=origin)


@pytest.mark.parametrize("original", ["TRUE", "FALSE"])
def test_unverified_opinion_preserves_audit_without_decisive_vote(validator, monkeypatch, original):
    monkeypatch.setattr(validator, "VALIDATOR_TYPE", validator.ValidatorType.RAG_EVIDENCE_VALIDATION)
    sources = [{"source_id": "source-1", "url": "https://example.test/report", "contexts": [
        {"context_id": "context-1", "text": "Texto recuperado exacto.", "citation_eligible": True}
    ]}]
    claims = [{"context_id": "context-invented", "supports": original == "TRUE"}]
    monkeypatch.setattr(validator, "fetch_evidences_for_payload", lambda payload: (sources, {"evidences": sources}))
    monkeypatch.setattr(validator, "payload_context_for_prompt", lambda payload: "Contexto")
    monkeypatch.setattr(validator, "ai_validator", SimpleNamespace(verificar_asercion=lambda *args: "response"))
    monkeypatch.setattr(validator, "parse_validator_api_response", lambda text: (
        validator.Validacion[original], "Razonamiento original", {"evidence_used": claims}))
    payload = SimpleNamespace(mode="LIGHT", assertion=SimpleNamespace(assertion_id="4", text="Afirmacion"))
    verdict, description, extras, response = validator.validate_payload_v2(payload)
    assert verdict == validator.Validacion.UNKNOWN
    assert extras["evidence_used"] == []
    assert "CONTEXT_NOT_RETRIEVED" in [issue["code"] for issue in extras["evidence_validation"]["issues"]]
    assert original in description
    assert response["evidences"] == sources


@pytest.mark.parametrize("validator_type", [1, 2, 4])
def test_non_rag_calls_neither_dependency(validator, monkeypatch, validator_type):
    monkeypatch.setattr(validator, "VALIDATOR_TYPE", validator.ValidatorType(validator_type))
    monkeypatch.setattr(validator.httpx, "post", lambda *args, **kwargs: pytest.fail("external dependency called"))
    assert validator.fetch_evidences_for_payload(minimal_payload()) == ([], None)


def test_direct_llm_search_requires_an_implemented_online_provider(validator, monkeypatch):
    monkeypatch.setattr(validator, "VALIDATOR_TYPE", validator.ValidatorType.LLM_SEARCH_VALIDATION)
    monkeypatch.setattr(validator, "AI_PROVIDER", "gemini")
    with pytest.raises(RuntimeError, match="requires AI_PROVIDER=openrouter"):
        validator.build_ai_validator()

    monkeypatch.setattr(validator, "AI_PROVIDER", "openrouter")
    assert validator.openrouter_model_for_current_type("openai/gpt-5-mini") == "openai/gpt-5-mini:online"
    assert validator.openrouter_model_for_current_type("openai/gpt-5-mini:online") == "openai/gpt-5-mini:online"


def routed_source():
    return {
        "domain": "idescat.cat", "source_type": "STATISTICAL_OFFICE", "authority_level": "REGIONAL_PRIMARY",
        "jurisdictions": [{"scope": "REGION", "country_code": "ES", "region_code": "ES-CT"}],
        "topic_codes": ["DEMOGRAPHY"], "evidence_kinds": ["STATISTICAL_DATA"], "languages": ["ca"],
        "route_score": 0.95, "rank": 1, "reason": "official", "profile_version": "source-router-v2",
    }


@pytest.mark.parametrize("diagnostic", [None, "CLASSIFICATION_PARTIAL", "PROFILE_FALLBACK"])
def test_rag_local_calls_router_then_evidence(validator, monkeypatch, diagnostic):
    monkeypatch.setattr(validator, "VALIDATOR_TYPE", validator.ValidatorType.RAG_EVIDENCE_VALIDATION)
    monkeypatch.setenv("EVIDENCE_SEARCH_STRATEGY", "LOCAL")
    calls = []

    class Response:
        def __init__(self, body): self.body = body
        def raise_for_status(self): return None
        def json(self): return self.body

    def post(url, json, timeout):
        calls.append((url, json))
        if "source-router" in url:
            return Response({"route_key": "k", "route_state": "MISSING", "router_version": "v2", "sources": [routed_source()],
                             "degraded": diagnostic is not None, "diagnostic_code": diagnostic,
                             "diagnostics": {"failed_domains": ["bad.example"] if diagnostic else []}})
        assert json["search_policy"]["strategy"] == "LOCAL"
        assert json["search_policy"]["preferred_sources"][0]["domain"] == "idescat.cat"
        assert json["origin_document"]["domain"] == "publisher.test"
        return Response({"evidences": [{"url": "https://idescat.cat/data"}]})

    monkeypatch.setattr(validator.httpx, "post", post)
    evidences, response = validator.fetch_evidences_for_payload(minimal_payload())
    assert len(calls) == 2
    assert "source-router" in calls[0][0] and "evidence-search" in calls[1][0]
    assert evidences == [{"url": "https://idescat.cat/data"}]
    assert response["route"]["diagnostic_code"] == diagnostic
    assert response["route"]["diagnostics"]["failed_domains"] == (["bad.example"] if diagnostic else [])


def test_source_router_http_status_is_preserved_as_retryable(validator, monkeypatch):
    request = validator.httpx.Request("POST", "http://source-router/routes/resolve")
    response = validator.httpx.Response(500, request=request, json={"detail": "classification failed"})

    def post(*args, **kwargs):
        raise validator.httpx.HTTPStatusError("server error", request=request, response=response)

    monkeypatch.setattr(validator.httpx, "post", post)
    with pytest.raises(validator.SourceRouterRequestError) as captured:
        validator.resolve_local_sources(minimal_payload())

    failure = validator.ValidationExecutionFailure("SOURCE_ROUTER", captured.value, [], None)
    details = validator.validation_error_details(failure)
    assert details.code == "SOURCE_ROUTER_HTTP_500"
    assert details.status_code == 500
    assert details.retryable is True
    assert details.message == "classification failed"


@pytest.mark.parametrize("strategy", ["EXT_OFFICIAL_FIRST", "EXT_ONLY_OFFICIAL"])
def test_rag_external_strategy_skips_router(validator, monkeypatch, strategy):
    monkeypatch.setattr(validator, "VALIDATOR_TYPE", validator.ValidatorType.RAG_EVIDENCE_VALIDATION)
    monkeypatch.setenv("EVIDENCE_SEARCH_STRATEGY", strategy)
    calls = []

    class Response:
        def raise_for_status(self): return None
        def json(self): return {"evidences": []}

    def post(url, json, timeout):
        calls.append((url, json))
        return Response()

    monkeypatch.setattr(validator.httpx, "post", post)
    validator.fetch_evidences_for_payload(minimal_payload())
    assert len(calls) == 1 and "evidence-search" in calls[0][0]
    assert calls[0][1]["search_policy"]["strategy"] == strategy
    assert calls[0][1]["search_policy"]["preferred_sources"] == []
