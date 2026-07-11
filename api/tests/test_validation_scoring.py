from common.models.veredicto import Validacion
from common.utils.scoring import calculate_assertion_result


def test_scoring_excludes_error_responses_from_scores():
    result = calculate_assertion_result(
        "1",
        {
            "validator-ok": {
                "approval": Validacion.TRUE,
                "execution_status": "COMPLETED",
            },
            "validator-error": {
                "approval": None,
                "execution_status": "ERROR",
                "error": "Unauthorized",
            },
        },
    )

    assert result["winner"] == "TRUE"
    assert result["scores"] == {"TRUE": 0.25, "FALSE": 0.0, "UNKNOWN": 0.0}
    assert result["validations_count"] == 1
    assert result["responses_count"] == 2
    assert result["errors_count"] == 1
    assert result["excluded_validators"] == ["validator-error"]


def test_scoring_with_only_errors_has_no_winner():
    result = calculate_assertion_result(
        "1",
        {
            "validator-error": {
                "approval": None,
                "execution_status": "ERROR",
            }
        },
    )

    assert result["winner"] is None
    assert result["validations_count"] == 0
    assert result["responses_count"] == 1
    assert result["errors_count"] == 1
    assert result["scores"] == {"TRUE": 0.0, "FALSE": 0.0, "UNKNOWN": 0.0}
