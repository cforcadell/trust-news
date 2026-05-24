from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from common.models.async_models import Assertion, ValidationMode, ValidatorConfig
from common.models.veredicto import Validacion


class EventRecord(BaseModel):
    order_id: str
    action: str
    topic: str
    timestamp: int | str | float
    payload: Dict[str, Any] = Field(default_factory=dict)


class ValidationRecord(BaseModel):
    approval: Validacion
    text: str = ""
    tx_hash: Optional[str] = None
    validator_alias: str = ""
    validator_config: Optional[Dict[str, Any]] = None
    validation_mode: Optional[ValidationMode] = None
    category: Optional[int] = None
    assertion_index: Optional[int] = None
    correlation_id: Optional[str] = None
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_used: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: Optional[float | str] = None
    error: Optional[str] = None
    response_time_seconds: Optional[float] = None


OrderValidationMap = Dict[str, Dict[str, ValidationRecord]]


class ValidatorAssignment(BaseModel):
    idAssertion: str
    validatorAddresses: List[str] = Field(default_factory=list)
    text: Optional[str] = None
    categoryId: Optional[int] = None


class AssertionResultDetail(BaseModel):
    validator: str
    validator_type: str
    validator_type_weight: float
    reputation: float
    effective_weight: float
    result: str
    description: str = ""
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_used: List[Dict[str, Any]] = Field(default_factory=list)


class AssertionResult(BaseModel):
    assertion_id: str
    scores: Dict[str, float] = Field(default_factory=lambda: {"TRUE": 0.0, "FALSE": 0.0, "UNKNOWN": 0.0})
    winner: str = "UNKNOWN"
    validations_count: int = 0
    details: List[AssertionResultDetail] = Field(default_factory=list)


class OrderDocument(BaseModel):
    order_id: str
    text: str = ""
    assertions: List[Assertion] = Field(default_factory=list)
    validation_mode: ValidationMode = ValidationMode.BLOCKCHAIN
    status: Optional[str] = None
    validators: List[ValidatorAssignment] = Field(default_factory=list)
    validation_requests: Dict[str, List[str]] = Field(default_factory=dict)
    validators_pending: int = 0
    validations: Dict[str, Dict[str, Dict[str, Any]]] = Field(default_factory=dict)
    assertion_results: Dict[str, AssertionResult] = Field(default_factory=dict)
    created_at: Optional[datetime | str] = None
    updated_at: Optional[datetime | str] = None


class ValidatorCacheEntry(BaseModel):
    validator: str
    ipfs_hash: Optional[str] = None
    config: Optional[ValidatorConfig | Dict[str, Any]] = None
    categories: List[Any] = Field(default_factory=list)
    validator_type: Optional[int | str] = None
    reputation: float = 1.0
    updated_at: Optional[str] = None
    metrics_reset_at: Optional[str] = None
    source: Optional[str] = None
