import itertools
import math

import pytest

from common.models.async_models import ValidatorType
from common.models.order_models import AssertionResult
from common.models.veredicto import Validacion
from common.utils.scoring import (
    CONSENSUS_POLICY,
    calculate_assertion_result,
    validation_weight_snapshot,
)


def completed(verdict, weight=0.25, mode=None):
    value = {
        "approval": verdict,
        "execution_status": "COMPLETED",
        "validator_type": "LLM_MEMORY_VALIDATION",
        "validator_type_weight": weight,
        "reputation_at_validation": 1.0,
        "effective_weight": weight,
        "weights_policy_version": "validator-weights-v1",
    }
    if mode:
        value["validation_mode"] = mode
    return value


def errored():
    return {"approval": None, "execution_status": "ERROR", "error": "failed"}


@pytest.mark.parametrize(
    ("votes", "verdict", "decision_status", "reason_code"),
    [
        ([Validacion.TRUE] * 3, "TRUE", "CONSENSUS", "ALL_DECISIVE_AGREE_TRUE"),
        ([Validacion.FALSE] * 3, "FALSE", "CONSENSUS", "ALL_DECISIVE_AGREE_FALSE"),
        ([Validacion.TRUE, Validacion.FALSE], "UNKNOWN", "NO_CONSENSUS", "TRUE_FALSE_WEIGHT_TIE"),
        ([Validacion.TRUE, Validacion.FALSE, Validacion.UNKNOWN], "UNKNOWN", "NO_CONSENSUS", "TRUE_FALSE_WEIGHT_TIE"),
        ([Validacion.UNKNOWN] * 3, "UNKNOWN", "INSUFFICIENT_EVIDENCE", "NO_DECISIVE_VALIDATIONS"),
        ([Validacion.FALSE, Validacion.UNKNOWN], "UNKNOWN", "INSUFFICIENT_EVIDENCE", "DECISIVE_COVERAGE_TOO_LOW"),
        ([Validacion.FALSE, Validacion.FALSE, Validacion.UNKNOWN], "FALSE", "CONSENSUS", "ALL_DECISIVE_AGREE_FALSE"),
    ],
)
def test_consensus_v2_decisions(votes, verdict, decision_status, reason_code):
    result = calculate_assertion_result(
        "1", {f"validator-{index}": completed(vote) for index, vote in enumerate(votes)}
    )

    assert result["verdict"] == verdict
    assert result["decision_status"] == decision_status
    assert result["reason_code"] == reason_code
    assert result["winner"] == (verdict if verdict in {"TRUE", "FALSE"} else None)
    assert result["consensus_policy"] == CONSENSUS_POLICY
    assert result["consensus_policy_version"] == "consensus-v2"


def test_raw_weights_distribution_and_counts_are_explicit():
    result = calculate_assertion_result(
        "1",
        {
            "rag": completed(Validacion.TRUE, 1.0),
            "search": completed(Validacion.FALSE, 0.5),
            "abstains": completed(Validacion.UNKNOWN, 0.25),
            "error": errored(),
        },
    )

    assert result["verdict"] == "TRUE"
    assert result["decision_status"] == "WEIGHTED_MAJORITY"
    assert result["scores"] == {"TRUE": 1.0, "FALSE": 0.5, "UNKNOWN": 0.25}
    assert result["distribution"] == {
        "raw_weight": {"TRUE": 1.0, "FALSE": 0.5, "UNKNOWN": 0.25},
        "decisive_share": {"TRUE": 0.666666666667, "FALSE": 0.333333333333},
        "decisive_coverage": 0.857142857143,
        "abstention_share": 0.142857142857,
        "decision_margin": 0.333333333333,
    }
    assert result["counts"] == {
        "responses": 4,
        "completed": 3,
        "decisive": 2,
        "abstentions": 1,
        "errors": 1,
    }
    assert result["excluded_validators"] == ["error"]


def test_weighted_majority_with_two_false_validator_types():
    result = calculate_assertion_result(
        "1",
        {
            "rag": completed(Validacion.TRUE, 1.0),
            "search": completed(Validacion.FALSE, 0.5),
            "memory": completed(Validacion.FALSE, 0.25),
        },
    )
    assert (result["verdict"], result["decision_status"]) == ("TRUE", "WEIGHTED_MAJORITY")


def test_only_errors_are_not_votes_or_abstentions():
    result = calculate_assertion_result("1", {"b": errored(), "a": errored(), "c": errored()})

    assert result["verdict"] == "UNKNOWN"
    assert result["winner"] is None
    assert result["decision_status"] == "NO_VALID_RESPONSES"
    assert result["counts"] == {"responses": 3, "completed": 0, "decisive": 0, "abstentions": 0, "errors": 3}
    assert result["scores"] == {"TRUE": 0.0, "FALSE": 0.0, "UNKNOWN": 0.0}


def test_no_responses_has_distinct_stable_reason():
    result = calculate_assertion_result("1", {})
    assert result["decision_status"] == "NO_VALID_RESPONSES"
    assert result["reason_code"] == "NO_COMPLETED_VALIDATIONS"


def test_errors_do_not_reduce_decisive_coverage():
    result = calculate_assertion_result(
        "1", {"ok": completed(Validacion.TRUE), "error-1": errored(), "error-2": errored()}
    )
    assert (result["verdict"], result["decision_status"]) == ("TRUE", "CONSENSUS")
    assert result["distribution"]["decisive_coverage"] == 1.0


def test_result_is_independent_of_validator_order():
    items = [
        ("rag", completed(Validacion.TRUE, 1.0)),
        ("search", completed(Validacion.FALSE, 0.5)),
        ("memory", completed(Validacion.UNKNOWN, 0.25)),
    ]
    results = [calculate_assertion_result("1", dict(permutation)) for permutation in itertools.permutations(items)]
    assert all(result == results[0] for result in results)


def test_nearly_equal_floats_are_an_explicit_tie():
    result = calculate_assertion_result(
        "1",
        {
            "true": completed(Validacion.TRUE, 1.0000000001),
            "false": completed(Validacion.FALSE, 1.0000000002),
        },
    )
    assert result["winner"] is None
    assert result["decision_status"] == "NO_CONSENSUS"


@pytest.mark.parametrize("bad_weight", [-1, math.nan, math.inf, -math.inf, "not-a-number"])
def test_corrupt_snapshot_weights_are_neutralized(bad_weight):
    result = calculate_assertion_result("1", {"bad": completed(Validacion.TRUE, bad_weight)})
    assert result["scores"]["TRUE"] == 0.0
    assert result["verdict"] == "UNKNOWN"
    assert result["decision_status"] == "INSUFFICIENT_EVIDENCE"


def test_legacy_records_use_explicit_dynamic_fallback():
    legacy = {
        "approval": Validacion.TRUE,
        "execution_status": "COMPLETED",
        "validator_config": {"validator_type": int(ValidatorType.RAG_EVIDENCE_VALIDATION), "reputation": 0.8},
    }
    result = calculate_assertion_result("1", {"legacy": legacy}, validator_type_weights={"RAG_EVIDENCE_VALIDATION": 0.75})
    assert result["scores"]["TRUE"] == 0.6
    assert result["legacy_dynamic_weight"] is True
    assert result["details"][0]["legacy_dynamic_weight"] is True


def test_frozen_snapshot_does_not_change_with_current_config():
    frozen = completed(Validacion.TRUE, 0.75)
    first = calculate_assertion_result("1", {"frozen": frozen}, validator_type_weights={"LLM_MEMORY_VALIDATION": 0.1})
    second = calculate_assertion_result("1", {"frozen": frozen}, validator_type_weights={"LLM_MEMORY_VALIDATION": 1.0})
    assert first == second
    assert first["legacy_dynamic_weight"] is False


def test_light_and_blockchain_use_the_same_consensus():
    light = {
        "a": completed(Validacion.TRUE, 1.0, "LIGHT"),
        "b": completed(Validacion.FALSE, 0.5, "LIGHT"),
    }
    blockchain = {
        key: {**value, "validation_mode": "BLOCKCHAIN"} for key, value in light.items()
    }
    assert calculate_assertion_result("1", light) == calculate_assertion_result("1", blockchain)


def test_snapshot_freezes_default_type_weight_and_reputation():
    snapshot = validation_weight_snapshot(
        {"validator_type": int(ValidatorType.HUMAN), "reputation": 0.5},
    )
    assert snapshot == {
        "validator_type": "HUMAN",
        "validator_type_weight": 0.1,
        "reputation_at_validation": 0.5,
        "effective_weight": 0.05,
        "weights_policy_version": "validator-weights-v1",
        "legacy_dynamic_weight": False,
    }


@pytest.mark.parametrize("bad_value", [-1, math.nan, math.inf, "invalid"])
def test_snapshot_neutralizes_corrupt_reputation_and_configured_weight(bad_value):
    bad_reputation = validation_weight_snapshot(
        {"validator_type": int(ValidatorType.HUMAN), "reputation": bad_value}
    )
    bad_type_weight = validation_weight_snapshot(
        {"validator_type": int(ValidatorType.HUMAN), "reputation": 1.0},
        {"HUMAN": bad_value},
    )
    assert bad_reputation["effective_weight"] == 0.0
    assert bad_type_weight["effective_weight"] == 0.0


def test_snapshot_neutralizes_overflowing_effective_weight():
    snapshot = validation_weight_snapshot(
        {"validator_type": int(ValidatorType.HUMAN), "reputation": 1e308},
        {"HUMAN": 1e308},
    )
    assert snapshot["effective_weight"] == 0.0


def test_legacy_assertion_result_model_remains_readable():
    legacy = AssertionResult.model_validate(
        {
            "assertion_id": "1",
            "scores": {"TRUE": 0.25, "FALSE": 0.0, "UNKNOWN": 0.0},
            "winner": "TRUE",
            "details": [
                {
                    "validator": "old",
                    "validator_type": "LLM_MEMORY_VALIDATION",
                    "validator_type_weight": 0.25,
                    "reputation": 1.0,
                    "effective_weight": 0.25,
                    "result": "TRUE",
                }
            ],
        }
    )
    assert legacy.winner == "TRUE"
    assert legacy.details[0].reputation_at_validation is None
