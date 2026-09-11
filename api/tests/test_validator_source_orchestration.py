import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(scope="module")
def validator(monkeypatch_module):
    return monkeypatch_module


@pytest.fixture(scope="module")
def monkeypatch_module():
    import os

    root = Path(__file__).resolve().parents[2]
    os.environ.update({
        "ACCOUNT_ADDRESS": "0x0000000000000000000000000000000000000001",
        "CONTRACT_ADDRESS": "0x0000000000000000000000000000000000000002",
        "CONTRACT_ABI_PATH": str(root / "smart-contracts/artifacts/contracts/TrustNews.sol/TrustNews.json"),
        "RPC_URL": "http://127.0.0.1:1", "PRIVATE_KEY": "0x" + "1" * 64,
        "VALIDATOR_TYPE": "4", "AI_PROVIDER": "none",
    })
    path = root / "api/validate-asertions/main.py"
    spec = importlib.util.spec_from_file_location("source_orchestration_validator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def minimal_payload():
    assertion = SimpleNamespace(
        categoryId=4, subcategory="DEMOGRAPHICS",
        search_hints=SimpleNamespace(preferred_source_types=["statistics"]),
        context=SimpleNamespace(
            locations=[SimpleNamespace(name="Catalunya", country_code="ES", region_code="ES-CT", scope="regional", origin=SimpleNamespace(value="explicit"), confidence=1)],
            entities=[], language="ca", jurisdiction="regional",
        ),
        model_dump=lambda mode=None: {"assertion_id": "1", "assertion_index": 0, "text": "Population", "categoryId": 4, "subcategory": "DEMOGRAPHICS", "context": {}, "search_hints": {}, "context_confidence": {}},
    )
    return SimpleNamespace(assertion=assertion)


def test_non_rag_calls_neither_dependency(validator, monkeypatch):
    validator.VALIDATOR_TYPE = validator.ValidatorType.LLM_MEMORY_VALIDATION
    monkeypatch.setattr(validator.httpx, "post", lambda *args, **kwargs: pytest.fail("external dependency called"))
    assert validator.fetch_evidences_for_payload(minimal_payload()) == ([], None)


def test_rag_local_calls_router_then_evidence(validator, monkeypatch):
    validator.VALIDATOR_TYPE = validator.ValidatorType.RAG_EVIDENCE_VALIDATION
    monkeypatch.setenv("EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS", "LOCAL")
    calls = []

    class Response:
        def __init__(self, body): self.body = body
        def raise_for_status(self): return None
        def json(self): return self.body

    def post(url, json, timeout):
        calls.append((url, json))
        if "source-router" in url:
            return Response({"route_key": "k", "route_state": "MISSING", "router_version": "v1", "sources": [{"domain": "idescat.cat"}]})
        assert json["search_policy"]["include_domains"] == ["idescat.cat"]
        assert json["search_policy"]["use_preferred_domains"] == "LOCAL"
        # evidence-search receives the ordinary policy, then constrains it to
        # routed domains before planning provider calls.
        assert json["search_policy"]["fallback_to_general_search"] is True
        return Response({"evidences": [{"url": "https://idescat.cat/data"}]})

    monkeypatch.setattr(validator.httpx, "post", post)
    evidences, response = validator.fetch_evidences_for_payload(minimal_payload())
    assert ["source-router" in calls[0][0], "evidence-search" in calls[1][0]] == [True, True]
    assert evidences[0]["url"].startswith("https://idescat.cat")
    assert response["route"]["route_key"] == "k"


def test_rag_prompt_includes_auditable_source_context(validator):
    validator.VALIDATOR_TYPE = validator.ValidatorType.RAG_EVIDENCE_VALIDATION

    prompt = validator.build_prompt_content(
        "Catalunya supera los ocho millones de habitantes.",
        "Noticia publicada en 2025.",
        [{
            "source_id": "source-1",
            "title": "Població. Idescat",
            "url": "https://www.idescat.cat/poblacio",
            "domain": "idescat.cat",
            "source_type": "official_statistics",
            "trust_score": 0.95,
            "why_selected": "regional primary source",
            "contexts": [{
                "context_id": "ctx-1",
                "origin": "raw_content",
                "score": 0.91,
                "included_chunk_ids": ["chunk-1"],
                "text": "La població de Catalunya és de 8.124.000 habitants.",
            }],
        }],
    )

    assert "Evidencias proporcionadas:" in prompt
    assert "source_id: source-1" in prompt
    assert "url: https://www.idescat.cat/poblacio" in prompt
    assert "context_id: ctx-1" in prompt
    assert "included_chunk_ids: ['chunk-1']" in prompt
    assert "La població de Catalunya és de 8.124.000 habitants." in prompt
    assert "Aserción a validar:\nCatalunya supera los ocho millones de habitantes." in prompt


@pytest.mark.parametrize("mode", ["NONE", "EXT_OFFICIAL_FIRST", "EXT_ONLY_OFFICIAL"])
def test_rag_external_modes_skip_router(validator, monkeypatch, mode):
    validator.VALIDATOR_TYPE = validator.ValidatorType.RAG_EVIDENCE_VALIDATION
    monkeypatch.setenv("EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS", mode)
    calls = []

    class Response:
        def raise_for_status(self): return None
        def json(self): return {"evidences": []}

    def post(url, json, timeout):
        calls.append(url)
        return Response()

    monkeypatch.setattr(validator.httpx, "post", post)
    validator.fetch_evidences_for_payload(minimal_payload())
    assert len(calls) == 1 and "evidence-search" in calls[0]
