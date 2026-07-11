import pytest
from pydantic import ValidationError

from common.models.async_models import (
    LightValidationRequest,
    LightValidationResponse,
    PublishRequest,
    PublishWithAssertionsRequest,
    ValidationCompletedResponse,
    ValidationExecutionStatus,
    ValidationMode,
)
from common.models.veredicto import Validacion


def test_publish_request_defaults_to_blockchain():
    req = PublishRequest(text="news")
    assert req.validation_mode == ValidationMode.BLOCKCHAIN


def test_publish_request_accepts_light():
    req = PublishRequest(text="news", validation_mode="LIGHT")
    assert req.validation_mode == ValidationMode.LIGHT


def test_publish_request_rejects_invalid_mode():
    with pytest.raises(ValidationError):
        PublishRequest(text="news", validation_mode="FAST")


def test_publish_with_assertions_defaults_to_blockchain():
    req = PublishWithAssertionsRequest(
        text="news",
        assertions=[{"idAssertion": "1", "text": "claim", "categoryId": 1}],
    )
    assert req.validation_mode == ValidationMode.BLOCKCHAIN


def test_light_kafka_contracts_include_correlation_fields():
    request = LightValidationRequest(
        order_id="order-1",
        payload={
            "order_id": "order-1",
            "assertion_index": 0,
            "idAssertion": "1",
            "assertion_text": "claim",
            "categoryId": 1,
            "validator_id": "validator-1",
            "correlation_id": "order-1:1:validator-1",
            "timestamp": "2026-05-16T00:00:00+00:00",
        },
    )
    response = LightValidationResponse(
        order_id="order-1",
        payload={
            "order_id": "order-1",
            "assertion_index": request.payload.assertion_index,
            "idAssertion": request.payload.idAssertion,
            "validator_id": request.payload.validator_id,
            "categoryId": request.payload.categoryId,
            "verdict": Validacion.TRUE,
            "description": "ok",
            "timestamp": "2026-05-16T00:00:01+00:00",
            "correlation_id": request.payload.correlation_id,
            "execution_status": ValidationExecutionStatus.COMPLETED,
        },
    )

    assert request.payload.validation_mode == ValidationMode.LIGHT
    assert response.payload.validation_mode == ValidationMode.LIGHT
    assert response.payload.correlation_id == "order-1:1:validator-1"


def test_light_error_contract_has_no_verdict_and_keeps_evidence():
    response = LightValidationResponse(
        order_id="order-error",
        payload={
            "order_id": "order-error",
            "assertion_index": 0,
            "idAssertion": "1",
            "validator_id": "validator-1",
            "categoryId": 1,
            "verdict": None,
            "description": "Unauthorized",
            "evidence_search_response": {"evidences": [{"url": "https://example.test"}]},
            "timestamp": "2026-05-16T00:00:01+00:00",
            "correlation_id": "order-error:1:validator-1",
            "execution_status": ValidationExecutionStatus.ERROR,
            "error": "Unauthorized",
            "error_details": {
                "stage": "LLM_REQUEST",
                "code": "LLM_HTTP_401",
                "message": "Unauthorized",
                "retryable": False,
                "status_code": 401,
            },
        },
    )

    assert response.payload.verdict is None
    assert response.payload.execution_status == ValidationExecutionStatus.ERROR
    assert response.payload.evidence_search_response["evidences"]


def test_blockchain_error_contract_has_no_verdict():
    response = ValidationCompletedResponse(
        payload={
            "postId": "42",
            "idValidator": "validator-1",
            "idAssertion": "1",
            "approval": None,
            "text": "Evidence provider failed",
            "execution_status": ValidationExecutionStatus.ERROR,
            "error": "Evidence provider failed",
            "error_details": {
                "stage": "EVIDENCE_SEARCH",
                "code": "EVIDENCE_SEARCH_HTTP_502",
                "message": "Evidence provider failed",
                "retryable": True,
                "status_code": 502,
            },
        }
    )

    assert response.payload.approval is None
    assert response.payload.execution_status == ValidationExecutionStatus.ERROR
