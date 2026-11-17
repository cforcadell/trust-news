import os
import ssl
from typing import Dict, Type

from pydantic import BaseModel

from common.models.async_models import (
    AssertionsGeneratedResponse,
    AssertionsNotGeneratedResponse,
    BlockchainRegistrationFailedResponse,
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
ACTION_BLOCKCHAIN_REGISTRATION_FAILED = "blockchain_registration_failed"
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
DEFAULT_KAFKA_BOOTSTRAP = "kafka.infra.svc.cluster.local:9092"

ACTION_TO_MODEL_RESPONSE: Dict[str, Type[BaseModel]] = {
    ACTION_ASSERTIONS_GENERATED: AssertionsGeneratedResponse,
    ACTION_ASSERTIONS_NOT_GENERATED: AssertionsNotGeneratedResponse,
    ACTION_IPFS_UPLOADED: IpfsUploadedResponse,
    ACTION_BLOCKCHAIN_REGISTERED: BlockchainRegisteredResponse,
    ACTION_BLOCKCHAIN_REGISTRATION_FAILED: BlockchainRegistrationFailedResponse,
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
    protocol = (security_protocol or os.getenv("KAFKA_SECURITY_PROTOCOL", "SSL")).upper()
    if protocol not in {"SSL", "SASL_SSL"}:
        raise ValueError(f"Kafka requires an encrypted security protocol, got {protocol!r}")
    ca_file = os.getenv("KAFKA_CA_FILE", "/etc/kafka-tls/ca.crt")
    if not os.path.isfile(ca_file):
        raise ValueError(f"Kafka CA file is missing: {ca_file}")
    tls = ssl.create_default_context(cafile=ca_file)
    tls.check_hostname = True
    tls.verify_mode = ssl.CERT_REQUIRED
    kwargs = {"security_protocol": protocol, "ssl_context": tls}
    if "SASL" in protocol:
        if not (username and password):
            raise ValueError("Kafka SASL credentials are incomplete")
        kwargs.update({
            "sasl_mechanism": mechanism or "PLAIN",
            "sasl_plain_username": username,
            "sasl_plain_password": password,
        })
    return kwargs


def kafka_admin_security_kwargs() -> dict:
    """The kafka-python adapter uses the same TLS contract as aiokafka."""
    protocol = os.getenv("KAFKA_SECURITY_PROTOCOL", "SSL").upper()
    if protocol != "SSL":
        raise ValueError("Kafka admin client requires SSL in S07a")
    ca_file = os.getenv("KAFKA_CA_FILE", "/etc/kafka-tls/ca.crt")
    if not os.path.isfile(ca_file):
        raise ValueError(f"Kafka CA file is missing: {ca_file}")
    return {"security_protocol": "SSL", "ssl_cafile": ca_file, "ssl_check_hostname": True}
