from common.models.async_models import (
    ValidatorType,
    get_validator_type_weight,
    normalize_validation_result,
)


def test_validator_type_has_no_legacy_aliases():
    for legacy_name in ("General_AI", "Trained_AI", "Dedicated_Agent", "Human"):
        assert legacy_name not in ValidatorType.__members__


def test_validator_type_weights():
    assert get_validator_type_weight(ValidatorType.LLM_MEMORY_VALIDATION) == 0.25
    assert get_validator_type_weight(ValidatorType.LLM_SEARCH_VALIDATION) == 0.5
    assert get_validator_type_weight(ValidatorType.RAG_EVIDENCE_VALIDATION) == 0.8
    assert get_validator_type_weight(ValidatorType.DETERMINISTIC_VALIDATION) == 1.0
    assert get_validator_type_weight(ValidatorType.HUMAN) == 0.1


def test_result_normalization():
    assert normalize_validation_result("SUPPORTED") == "UNKNOWN"
    assert normalize_validation_result("REFUTED") == "UNKNOWN"
    assert normalize_validation_result("INSUFFICIENT") == "UNKNOWN"
    assert normalize_validation_result(1) == "TRUE"
    assert normalize_validation_result(2) == "FALSE"
    assert normalize_validation_result(3) == "UNKNOWN"


def test_weighted_score_formula_divides_by_validator_count():
    validations = [
        (ValidatorType.LLM_MEMORY_VALIDATION, 1.0, "TRUE"),
        (ValidatorType.LLM_SEARCH_VALIDATION, 1.0, "TRUE"),
        (ValidatorType.RAG_EVIDENCE_VALIDATION, 1.0, "FALSE"),
    ]
    scores = {"TRUE": 0.0, "FALSE": 0.0, "UNKNOWN": 0.0}
    for validator_type, reputation, result in validations:
        scores[normalize_validation_result(result)] += get_validator_type_weight(validator_type) * reputation / len(validations)

    assert round(scores["TRUE"], 4) == 0.25
    assert round(scores["FALSE"], 4) == 0.2667
    assert max(scores, key=scores.get) == "FALSE"
