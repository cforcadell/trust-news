import json

import pytest

from evaluation import ROOT
from evaluation.core.artifacts import EvaluationError, write_json
from evaluation.core.datasets import load_datasets, validate_case
from evaluation.core.models import CaseResult


def resource():
    return {"schema_version": 2, "id": "example", "news": "Example", "tags": ["lang:es"],
            "assertions": [{"id": "one", "text": "Example", "expected_verdict": "UNKNOWN",
                            "tags": ["evidence:insufficient"]}]}


def test_old_datasets_load():
    cases = load_datasets([str(ROOT / "tests/data/benchmark/resources/cases")])
    assert {case["id"] for case in cases} >= {
        "eu-institutions-and-law-v1", "eu-renewable-energy-policy-v1",
    }


def test_v2_tags_and_optional_gold(tmp_path):
    path = tmp_path / "case.json"
    write_json(path, resource())
    assert load_datasets([str(path)], ["lang:es", "evidence:insufficient"])
    with pytest.raises(EvaluationError, match="No cases"):
        load_datasets([str(path)], ["lang:ca"])


@pytest.mark.parametrize("change", [
    {"expected_verdict": "MAYBE"}, {"reference_facts": "text"},
    {"reference_evidence": [{"text": ""}]}, {"tags": ["missing-family"]},
    {"expected_topic_code": "POLITICS"}, {"expected_evidence_kind": "LEGAL_DOCUMENT"},
])
def test_invalid_reference_rejected(change):
    case = resource()
    case["assertions"][0].update(change)
    with pytest.raises(EvaluationError):
        validate_case(case)


def test_secret_fields_not_persisted(tmp_path):
    path = tmp_path / "result.json"
    result = CaseResult("case", "GOLD_EVIDENCE", {}, {}).to_dict()
    result["validator"] = {"model": "model", "api_key": "secret", "nested": {"Authorization": "secret"}}
    write_json(path, result)
    data = path.read_text()
    assert "secret" not in data
    assert json.loads(data)["run_id"]


@pytest.mark.parametrize("verdict", [True, False, 1, 2, "1", "2", "verdadero", "falso"])
def test_v1_keeps_historical_verdict_aliases(verdict):
    case = resource()
    case["schema_version"] = "1"
    case["assertions"][0].update(expected_verdict=verdict, required_terms=["example"])
    validate_case(case)
