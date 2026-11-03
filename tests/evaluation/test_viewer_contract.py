"""The fixture must remain navigable and reject broken cross-record links."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from evaluation.viewer_contract import ContractError, validate_order_diagnostic
from evaluation.viewer.build import _validation_stages


VIEWER = Path(__file__).parent / "viewer"
VIEWER_FIXTURE = Path(__file__).resolve().parents[1] / "data/evaluation/resources/viewer-fixtures/order-diagnostic-v1.json"


@pytest.fixture
def example():
    return json.loads(VIEWER_FIXTURE.read_text(encoding="utf-8"))


def test_fixture_validates_and_covers_diagnostic_chain(example):
    assert validate_order_diagnostic(example) is example
    assert len(example["order"]["assertions"]) == 2
    assert len({v["validator_id"] for v in example["validations"]}) == 2
    first, second = example["validations"]
    assert first["stages"]["router"]["observations"]["cache_hit"] is True
    sources = first["stages"]["evidence_search"]["observations"]["sources"]
    assert any(source["fetch_status"] == "failed" for source in sources)
    chunks = sources[0]["chunks"]
    assert any(chunk["selected"] and chunk["text"] for chunk in chunks)
    assert any(not chunk["selected"] and chunk["text"] for chunk in chunks)
    assert second["stages"]["citations"]["checks"][0]["code"] == "INVALID_SOURCE_ID"
    assert second["stages"]["router"]["assessment"] == "NOT_EVALUATED"


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["validations"][0].update(assertion_id="missing"), "Unknown assertion_id"),
    (lambda d: d["artifact_refs"]["results"].pop(), "run_ids must match"),
    (lambda d: d["validations"][1]["stages"]["router"].pop("missing_reason"), "missing_reason"),
    (lambda d: d["validations"][0]["stages"]["evidence_search"]["checks"][0].update(
        observation_refs=["/validations/0/stages/evidence_search/observations/sources/99"]),
     "Unresolvable observation_ref"),
    (lambda d: d["artifact_refs"].update(order="../other-order.json"), "normalized path"),
])
def test_rejects_broken_navigation(example, mutate, message):
    invalid = deepcopy(example)
    mutate(invalid)
    with pytest.raises(ContractError, match=message):
        validate_order_diagnostic(invalid)


def test_fixture_conforms_to_json_schema_when_validator_available(example):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((VIEWER / "order-diagnostic-v1.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(example, schema)


def test_viewer_marks_llm_skipped_when_rag_received_no_citable_evidence():
    stages = _validation_stages({
        "expected": {"expected_verdict": "TRUE"},
        "retrieval": {"status": "COMPLETED", "evidences": []},
        "validator_output": {"effective_verdict": "UNKNOWN"},
        "grounding": {"validation": {"basis": "NO_CITABLE_EVIDENCE"}},
    })
    assert stages["llm"]["execution_status"] == "SKIPPED"
    assert stages["llm"]["assessment"] == "NOT_EVALUATED"
    assert stages["llm"]["checks"][0]["code"] == "NO_CITABLE_EVIDENCE"


def test_viewer_marks_retrieval_and_llm_skipped_when_router_has_no_sources():
    stages = _validation_stages({
        "expected": {"expected_verdict": "TRUE"},
        "router": {"status": "COMPLETED", "sources": []},
        "retrieval": {"status": "COMPLETED", "evidences": [],
                      "search_skipped": "no_eligible_local_sources"},
        "validator_output": {"effective_verdict": "UNKNOWN"},
        "grounding": {"validation": {"basis": "ROUTER_NO_SOURCE"}},
    })
    assert stages["evidence_search"]["execution_status"] == "SKIPPED"
    assert stages["evidence_search"]["checks"][0]["code"] == "ROUTER_NO_SOURCE"
    assert stages["llm"]["execution_status"] == "SKIPPED"
    assert stages["llm"]["checks"][0]["code"] == "ROUTER_NO_SOURCE"
