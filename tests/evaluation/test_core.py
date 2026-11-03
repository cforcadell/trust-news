import json

import pytest

from evaluation import ROOT
from evaluation.core.artifacts import EvaluationError, write_json
from evaluation.core.datasets import load_datasets, validate_case
from evaluation.core.models import CaseResult
from evaluation.core.common_metrics import match_assertions, missing_expected_numbers
from evaluation.core.orders import results_from_order


def resource():
    return {"schema_version": 2, "id": "example", "news": "Example", "tags": ["lang:es"],
            "assertions": [{"id": "one", "text": "Example", "expected_verdict": "UNKNOWN",
                            "tags": ["evidence:insufficient"]}]}


def test_active_and_historical_datasets_load_separately():
    active = load_datasets([str(ROOT / "tests/data/benchmark/resources/cases/official-gold-v0")])
    assert len(active) == 11
    assert all("suite:official-gold-v0" in case.get("tags", []) for case in active)

    historical = load_datasets([
        str(ROOT / "tests/data/benchmark/resources/cases/historical/pre-gold-v0")
    ])
    assert {case["id"] for case in historical} >= {
        "eu-institutions-and-law-v1", "eu-renewable-energy-policy-v1",
        "eu-news-2025-v2", "eu-official-statistics-2025-v2",
    }
    assert "eu-news-2025-v1" not in {case["id"] for case in historical}


def test_v2_tags_and_optional_gold(tmp_path):
    path = tmp_path / "case.json"
    write_json(path, resource())
    assert load_datasets([str(path)], ["lang:es", "evidence:insufficient"])
    with pytest.raises(EvaluationError, match="No cases"):
        load_datasets([str(path)], ["lang:ca"])


def test_approximate_value_annotations_are_validated():
    case = {"schema_version": 2, "id": "approx", "news": "Aproximadamente un cuarto.",
            "assertions": [{"id": "one", "text": "Fue 24,5 %.", "expected_verdict": "TRUE",
                            "approximate_values": [{"value": 24.5, "tolerance": 0.5,
                                                    "aliases": ["un cuarto"]}]}]}
    validate_case(case)
    case["assertions"][0]["approximate_values"][0]["tolerance"] = -1
    with pytest.raises(EvaluationError, match="invalid approximate value"):
        validate_case(case)


def test_missing_expected_numbers_parses_grouped_spanish_number():
    expected = {"text": "La población de España fue de 49.128.297 habitantes."}

    assert missing_expected_numbers(expected, expected["text"]) == []
    assert missing_expected_numbers(expected, "La población de España fue de 49.128.296 habitantes.") == [
        "49.128.297"
    ]


def test_numeric_conflict_is_linked_but_not_scored_as_same_assertion():
    case = {"schema_version": 2, "id": "dates", "news": "La norma se aplica desde 2018.",
            "assertions": [{"id": "wrong-date", "text": "La norma se aplica desde 2020.",
                            "expected_verdict": "FALSE", "required_terms": ["norma", "aplica"]}]}
    generated = [{"idAssertion": "1", "text": "La norma se aplica desde 2018."}]

    match = match_assertions(case, generated)[0]
    assert match["match_status"] == "INCOMPATIBLE"
    assert match["incompatibility_reasons"] == ["YEAR_CONFLICT"]

    rows = [row.to_dict() for row in results_from_order(case, {"order_id": "order", "assertions": generated})]
    scored = next(row for row in rows if row["provenance"]["scoring_eligible"] is True)
    observed = next(row for row in rows if row["provenance"]["scoring_eligible"] is False)
    assert scored["extraction"]["status"] == "EXTRACTION_ERROR"
    assert scored["extraction"]["match"]["anchor_match"] is False
    assert scored["metrics"]["validation"]["status"] == "NOT_EVALUATED"
    assert observed["extraction"]["status"] == "UNMATCHED_GENERATED_ASSERTION"


def test_full_date_conflict_is_detected_even_when_day_and_month_match():
    case = {"schema_version": 2, "id": "gdpr-date", "news": "RGPD", "assertions": [{
        "id": "wrong-date",
        "text": "El RGPD comenzó a aplicarse el 25 de mayo de 2020.",
        "expected_verdict": "FALSE",
        "required_terms": ["RGPD", "25 de mayo", "2020"],
    }]}
    generated = [{"idAssertion": "1", "text": "El RGPD comenzó a aplicarse el 25 de mayo de 2018."}]

    match = match_assertions(case, generated)[0]

    assert match["match_status"] == "INCOMPATIBLE"
    assert match["anchor_conflicts"] == ["DATE_CONFLICT"]
    assert match["expected_anchors"]["dates"] == ["2020-05-25"]
    assert match["generated_anchors"]["dates"] == ["2018-05-25"]


@pytest.mark.parametrize(("expected", "actual", "reason"), [
    ("La Directiva 2023/2413 fija un 42,5 % en 2030.",
     "La Directiva 2023/2413 fija un 45 % en 2030.", "PERCENTAGE_CONFLICT"),
    ("El Parlamento tiene 720 diputados elegidos en 27 Estados.",
     "Los diputados fueron elegidos en 27 Estados.", "REQUIRED_QUANTITY_MISSING:diputados"),
])
def test_typed_critical_anchors_prevent_unsafe_gold_inheritance(expected, actual, reason):
    case = {"schema_version": 2, "id": "anchors", "news": expected, "assertions": [{
        "id": "assertion", "text": expected, "expected_verdict": "TRUE",
        "required_terms": expected.split(),
    }]}

    match = match_assertions(case, [{"idAssertion": "1", "text": actual}])[0]

    assert match["match_status"] == "INCOMPATIBLE"
    assert reason in match["anchor_conflicts"]


def test_absolute_quantifier_is_compatible_with_one_hundred_percent_anchor():
    case = {"schema_version": 2, "id": "share", "news": "El 100 % fue renovable.", "assertions": [{
        "id": "assertion", "text": "El 100 % de la electricidad fue renovable.",
        "expected_verdict": "FALSE", "required_terms": ["100", "electricidad", "renovable"],
    }]}

    match = match_assertions(case, [{
        "idAssertion": "1", "text": "Toda la electricidad fue renovable."
    }])[0]

    assert match["match_status"] == "HEURISTIC_MATCH"
    assert match["anchor_match"] is True


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
