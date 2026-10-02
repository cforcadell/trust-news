"""The fixture must remain navigable and reject broken cross-record links."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from evaluation.viewer_contract import ContractError, validate_order_diagnostic


VIEWER = Path(__file__).parent / "viewer"


@pytest.fixture
def example():
    return json.loads((VIEWER / "fixtures/order-diagnostic-v1.json").read_text(encoding="utf-8"))


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
