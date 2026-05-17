import pytest
from pydantic import ValidationError

from common.async_models import (
    LightValidationRequest,
    LightValidationResponse,
    PublishRequest,
    PublishWithAssertionsRequest,
    ValidationMode,
)
from common.veredicto import Validacion


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
            "category": 1,
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
            "category": request.payload.category,
            "verdict": Validacion.TRUE,
            "description": "ok",
            "timestamp": "2026-05-16T00:00:01+00:00",
            "correlation_id": request.payload.correlation_id,
        },
    )

    assert request.payload.validation_mode == ValidationMode.LIGHT
    assert response.payload.validation_mode == ValidationMode.LIGHT
    assert response.payload.correlation_id == "order-1:1:validator-1"
