from typing import Dict, Type

from pydantic import BaseModel

from common.models.async_models import (
    AssertionsGeneratedResponse,
    AssertionsNotGeneratedResponse,
    BlockchainRegisteredResponse,
    IpfsUploadedResponse,
    LightValidationResponse,
    RequestValidationRequest,
    ValidationCompletedResponse,
    ValidatorConfigEvent,
)

ACTION_ASSERTIONS_GENERATED = "assertions_generated"
ACTION_ASSERTIONS_NOT_GENERATED = "assertions_not_generated"
ACTION_IPFS_UPLOADED = "ipfs_uploaded"
ACTION_BLOCKCHAIN_REGISTERED = "blockchain_registered"
ACTION_REQUEST_VALIDATION = "request_validation"
ACTION_VALIDATION_COMPLETED = "validation_completed"
ACTION_NEW_VALIDATOR_CONFIG = "new_validator_config"
ACTION_LIGHT_VALIDATION_REQUEST = "light_validation_request"
ACTION_LIGHT_VALIDATION_COMPLETED = "light_validation_completed"

DEFAULT_TOPIC_REQUESTS_GENERATE = "fake_news_requests_generate"
DEFAULT_TOPIC_REQUESTS_IPFS = "fake_news_requests_ipfs"
DEFAULT_TOPIC_REQUESTS_BLOCKCHAIN = "fake_news_requests_blockchain"
DEFAULT_TOPIC_REQUESTS_VALIDATE = "fake_news_requests_validate"
DEFAULT_TOPIC_LIGHT_VALIDATION_REQUESTS = "fake_news_requests_light_validation"
DEFAULT_TOPIC_RESPONSES = "fake_news_responses"
DEFAULT_KAFKA_BOOTSTRAP = "kafka:9092"

ACTION_TO_MODEL_RESPONSE: Dict[str, Type[BaseModel]] = {
    ACTION_ASSERTIONS_GENERATED: AssertionsGeneratedResponse,
    ACTION_ASSERTIONS_NOT_GENERATED: AssertionsNotGeneratedResponse,
    ACTION_IPFS_UPLOADED: IpfsUploadedResponse,
    ACTION_BLOCKCHAIN_REGISTERED: BlockchainRegisteredResponse,
    ACTION_VALIDATION_COMPLETED: ValidationCompletedResponse,
    ACTION_REQUEST_VALIDATION: RequestValidationRequest,
    ACTION_NEW_VALIDATOR_CONFIG: ValidatorConfigEvent,
    ACTION_LIGHT_VALIDATION_COMPLETED: LightValidationResponse,
}

ACTION_TO_QUOTA_MODEL: Dict[str, Type[BaseModel]] = {
    ACTION_ASSERTIONS_GENERATED: AssertionsGeneratedResponse,
    ACTION_VALIDATION_COMPLETED: ValidationCompletedResponse,
}

BILLABLE_SERVICES = {
    ACTION_ASSERTIONS_GENERATED: "news_generation",
    ACTION_VALIDATION_COMPLETED: "blockchain_validation",
}


def kafka_security_kwargs(
    security_protocol: str = "",
    mechanism: str = "",
    username: str = "",
    password: str = "",
    logger=None,
) -> dict:
    protocol = (security_protocol or "").upper()
    if "SASL" in protocol:
        if not (username and password):
            if logger:
                logger.warning(
                    "Kafka SASL requested but username/password are incomplete; "
                    "falling back to default PLAINTEXT client settings."
                )
            return {}
        return {
            "security_protocol": security_protocol,
            "sasl_mechanism": mechanism or "PLAIN",
            "sasl_plain_username": username,
            "sasl_plain_password": password,
        }

    kwargs = {}
    if security_protocol:
        kwargs["security_protocol"] = security_protocol
    return kwargs
