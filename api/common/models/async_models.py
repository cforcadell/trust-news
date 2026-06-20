from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator
from typing import List, Optional, Dict, Any
from enum import Enum, IntEnum
from common.models.veredicto import Validacion
from common.models.protocol_models import (
    AssertionContext,
    AssertionsDocumentV2,
    AssertionValidationPayloadV2,
    CategoryId,
    ContextConfidence,
    EnrichedAssertion,
    SearchHints,
    SourceDocumentStorage,
    build_assertions_document_v2,
    build_assertion_validation_payload_v2,
)


# ============================================================
# 🔹 COMMON MODELS
# ============================================================



class Multihash(BaseModel):
    """Represents a hash with its function and size (e.g., utilized for IPFS or SHA256 h./ashes)."""
    hash_function: str
    hash_size: str
    digest: str


class ValidatorAddress(BaseModel):
    address: str 


class Assertion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    """Represents one assertion with the on-chain category id as its identity."""
    idAssertion: Optional[str] = None
    text: str
    categoryId: CategoryId
    assertion_id: Optional[int | str] = None
    assertion_index: Optional[int] = None
    subcategory: str = "unknown"
    context: AssertionContext = Field(default_factory=AssertionContext)
    search_hints: SearchHints = Field(default_factory=SearchHints)
    context_confidence: ContextConfidence = Field(default_factory=ContextConfidence)

    def model_post_init(self, __context):
        if self.assertion_id is None and self.idAssertion is not None:
            self.assertion_id = self.idAssertion
        if self.idAssertion is None and self.assertion_id is not None:
            self.idAssertion = str(self.assertion_id)
        if self.assertion_index is None:
            try:
                self.assertion_index = max(0, int(self.assertion_id or self.idAssertion or 1) - 1)
            except Exception:
                self.assertion_index = 0

    def to_enriched(self) -> EnrichedAssertion:
        return EnrichedAssertion(
            assertion_id=self.assertion_id or self.idAssertion or 1,
            assertion_index=self.assertion_index or 0,
            text=self.text,
            categoryId=self.categoryId,
            subcategory=self.subcategory,
            context=self.context,
            search_hints=self.search_hints,
            context_confidence=self.context_confidence,
        )


class AssertionExtended(Assertion):
    """Extends Assertion with blockchain/validation details."""
    hash_asertion: Optional[str] = None
    validatorAddresses: Optional[List[ValidatorAddress]] = None


class Metadata(BaseModel):
    """Metadata about the document generation."""
    generated_by: str
    timestamp: float


class Document(BaseModel):
    """Document structure used before blockchain registration."""
    order_id: Optional[str] = None
    text: str
    assertions: List[Assertion]
    metadata: Optional[Metadata]


class VerifyInputModel(BaseModel):
    """Internal model to verify text and context."""
    text: str
    context: Optional[str] = None


class ValidationRegistrationModel(BaseModel):
    """Internal model for registering validation request details."""
    postId: str  # Kept as str for consistency
    assertion_id: str # Kept as str for consistency
    text: str
    context: Optional[str] = None


class ValidatorRegistrationInput(BaseModel):
    """Input model for registering a new validator."""
    name: str
    categories: Optional[List[CategoryId]] = None
    

    
class AsyncMessage(BaseModel):
    action: str
    order_id: str


class ValidationMode(str, Enum):
    BLOCKCHAIN = "BLOCKCHAIN"
    LIGHT = "LIGHT"


class ValidationExecutionStatus(str, Enum):
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


class ValidationErrorDetails(BaseModel):
    stage: str
    code: str
    message: str
    retryable: bool
    status_code: Optional[int] = None



# ============================================================
# 🔹 VALIDATOR CONFIG MODELS
# ============================================================
class ValidatorType(IntEnum):
    LLM_MEMORY_VALIDATION = 1
    LLM_SEARCH_VALIDATION = 2
    RAG_EVIDENCE_VALIDATION = 3
    DETERMINISTIC_VALIDATION = 4
    HUMAN = 5


class EvidencePreferredDomainsMode(str, Enum):
    NONE = "NONE"
    LOCAL = "LOCAL"
    EXT_OFFICIAL_FIRST = "EXT_OFFICIAL_FIRST"
    EXT_ONLY_OFFICIAL = "EXT_ONLY_OFFICIAL"



VALIDATOR_TYPE_WEIGHTS = {
    ValidatorType.LLM_MEMORY_VALIDATION: 0.25,
    ValidatorType.LLM_SEARCH_VALIDATION: 0.5,
    ValidatorType.RAG_EVIDENCE_VALIDATION: 1.0,
    ValidatorType.DETERMINISTIC_VALIDATION: 1.0,
    ValidatorType.HUMAN: 0.1,
}


def get_validator_type_weight(
    validator_type: ValidatorType | int | str | None,
    weights: dict | None = None,
) -> float:
    try:
        parsed = ValidatorType(int(validator_type))
    except Exception:
        try:
            parsed = ValidatorType[str(validator_type)]
        except Exception:
            parsed = ValidatorType.LLM_MEMORY_VALIDATION
    if weights:
        configured_weight = weights.get(parsed.name, weights.get(str(int(parsed))))
        if configured_weight is not None:
            try:
                return float(configured_weight)
            except (TypeError, ValueError):
                pass
    return VALIDATOR_TYPE_WEIGHTS.get(parsed, 0.25)


def default_validator_type_weights() -> dict[str, float]:
    return {validator_type.name: weight for validator_type, weight in VALIDATOR_TYPE_WEIGHTS.items()}


def normalize_validation_result(result: Any) -> str:
    raw = getattr(result, "name", result)
    if isinstance(raw, int):
        if raw == 1:
            return "TRUE"
        if raw == 2:
            return "FALSE"
        return "UNKNOWN"
    value = str(raw or "").upper()
    if value in {"TRUE"}:
        return "TRUE"
    if value in {"FALSE"}:
        return "FALSE"
    return "UNKNOWN"


class ValidatorStatus(IntEnum):
    Registered = 1
    Unregistered = 2
    Banned = 3


class ValidatorConfig(BaseModel):
    name: str
    type: ValidatorType = ValidatorType.LLM_MEMORY_VALIDATION
    provider: str
    model: str
    service_url: Optional[str] = None
    active_date: str
    updated_date: str
    end_date: Optional[str] = None
    status: ValidatorStatus = ValidatorStatus.Registered
    use_evidence_search: Optional[bool] = None
    online_search_enabled: Optional[bool] = None
    evidence_search_url: Optional[str] = None
    evidence_search_use_preferred_domains: Optional[EvidencePreferredDomainsMode] = None
    evidence_search_preferred_profile_id: Optional[str] = None


class ValidatorConfigOnChain(BaseModel):
    validator: str
    ipfs_hash: str
    config: Optional[ValidatorConfig] = None


class ValidatorConfigEventPayload(BaseModel):
    validator: str
    ipfs_hash: Optional[str] = None
    config: Optional[ValidatorConfig] = None
    categories: Optional[List[CategoryId]] = None
    source: Optional[str] = None
    timestamp: Optional[str] = None
    metrics_reset_at: Optional[str] = None


class ValidatorConfigEvent(BaseModel):
    action: str = "new_validator_config"
    order_id: str = ""
    payload: ValidatorConfigEventPayload


class ValidatorWithValidationsResponse(BaseModel):
    validator: str
    ipfs_hash: Optional[str] = None
    config: Optional[ValidatorConfig] = None
    validations: List[Dict[str, Any]] = Field(default_factory=list)

# ============================================================
# 🔹 GENERATE ASSERTIONS
# ============================================================

class TextoEntrada(BaseModel):
    text: str



class PublishRequest(BaseModel):
    text: str
    validation_mode: ValidationMode = ValidationMode.BLOCKCHAIN


class GenerateAssertionsPayload(BaseModel):
    text: str
    validation_mode: ValidationMode = ValidationMode.BLOCKCHAIN


class GenerateAssertionsRequest(BaseModel):
    action: str = "generate_assertions"
    order_id: str
    payload: GenerateAssertionsPayload


class AssertionGeneratedPayload(BaseModel):
    text: str
    assertions: List[Assertion]
    publisher: str
    validation_mode: ValidationMode = ValidationMode.BLOCKCHAIN
    assertions_document: Optional[AssertionsDocumentV2] = None


class AssertionsGeneratedResponse(BaseModel):
    action: str = "assertions_generated"
    order_id: str
    payload: AssertionGeneratedPayload


class AssertionsNotGeneratedPayload(BaseModel):
    text: str
    publisher: str
    error: str
    attempts: int


class AssertionsNotGeneratedResponse(BaseModel):
    action: str = "assertions_not_generated"
    order_id: str
    payload: AssertionsNotGeneratedPayload


# ============================================================
# 🔹 ASERCIONES YA GENERADAS
# ============================================================   
    
class PreGeneratedAssertion(Assertion):
    pass

class PublishWithAssertionsRequest(BaseModel):
    text: str
    assertions: List[PreGeneratedAssertion]
    validation_mode: ValidationMode = ValidationMode.BLOCKCHAIN

# ============================================================
# 🔹 UPLOAD IPFS
# ============================================================

class UploadIpfsPayload(BaseModel):
    document: Dict[str, Any] | Document | AssertionsDocumentV2


class UploadIpfsRequest(BaseModel):
    action: str = "upload_ipfs"
    order_id: str
    payload: UploadIpfsPayload


class IpfsUploadedPayload(BaseModel):
    cid: str


class IpfsUploadedResponse(BaseModel):
    action: str = "ipfs_uploaded"
    order_id: str
    payload: IpfsUploadedPayload


# ============================================================
# 🔹 REGISTER BLOCKCHAIN
# ============================================================

class RegisterBlockchainPayload(BaseModel):
    text: str
    cid: str
    assertions: List[Assertion]
    publisher: str


class RegisterBlockchainRequest(BaseModel):
    action: str = "register_blockchain"
    order_id: str
    payload: RegisterBlockchainPayload



class BlockchainRegisteredPayload(BaseModel):
    postId: str
    hash_text: str
    assertions: List[AssertionExtended]
    tx_hash: str


class BlockchainRegisteredResponse(BaseModel):
    action: str = "blockchain_registered"
    order_id: str
    payload: BlockchainRegisteredPayload




# ============================================================
# 🔹 REQUEST VALIDATION
# ============================================================

class RequestValidationPayload(BaseModel):
    """Payload to request a specific assertion validation (External Request)."""
    postId: str
    idValidator: str
    idAssertion: str
    text: str
    context: Optional[str] = None
    validation_mode: ValidationMode = ValidationMode.BLOCKCHAIN
    assertion_validation_payload: Optional[AssertionValidationPayloadV2] = None
    source_document_cid: Optional[str] = None


class RequestValidationRequest(BaseModel):
    action: str = "request_validation"
    order_id: str
    payload: RequestValidationPayload




# ============================================================
# 🔹 VALIDATION COMPLETED/FAILED
# ============================================================

class ValidationCompletedPayload(BaseModel):
    """Model for a completed or failed blockchain validation execution."""
    postId: str
    idValidator: str
    idAssertion: str
    approval: Optional[Validacion] = None
    text: str
    tx_hash: Optional[str] = None
    validator_alias: str = ""
    validation_mode: ValidationMode = ValidationMode.BLOCKCHAIN
    sources: Optional[List[Dict[str, Any]]] = None
    evidence_used: Optional[List[Dict[str, Any]]] = None
    evidence_search_response: Optional[Dict[str, Any]] = None
    search_policy: Optional[Dict[str, Any]] = None
    execution_status: ValidationExecutionStatus
    error: Optional[str] = None
    error_details: Optional[ValidationErrorDetails] = None

    @model_validator(mode="after")
    def require_execution_result(self):
        if self.execution_status == ValidationExecutionStatus.COMPLETED and self.approval is None:
            raise ValueError("Completed blockchain validation requires approval")
        if self.execution_status == ValidationExecutionStatus.ERROR and not self.error:
            raise ValueError("Failed blockchain validation requires error")
        return self


class ValidationCompletedResponse(BaseModel):
    action: str = "validation_completed"
    order_id: str = ""  # Optional - news-chain may not have order_id, only postId
    payload: ValidationCompletedPayload


    

# ============================================================
# 🔹 LIGHT VALIDATION KAFKA FLOW
# ============================================================

class LightValidationRequestPayload(BaseModel):
    order_id: str
    postId: Optional[str] = None
    validation_mode: ValidationMode = ValidationMode.LIGHT
    assertion_index: int
    idAssertion: str
    assertion_text: str
    categoryId: CategoryId
    validator_id: str
    original_text: Optional[str] = None
    client_id: Optional[str] = None
    correlation_id: str
    timestamp: str
    assertion_validation_payload: Optional[AssertionValidationPayloadV2] = None


class LightValidationRequest(BaseModel):
    action: str = "light_validation_request"
    order_id: str
    payload: LightValidationRequestPayload


class LightValidationResponsePayload(BaseModel):
    order_id: str
    validation_mode: ValidationMode = ValidationMode.LIGHT
    assertion_index: int
    idAssertion: str
    validator_id: str
    categoryId: CategoryId
    verdict: Optional[Validacion] = None
    description: str
    confidence: Optional[float | str] = None
    sources: Optional[List[Dict[str, Any]]] = None
    evidence_used: Optional[List[Dict[str, Any]]] = None
    assertion_validation_payload: Optional[Dict[str, Any]] = None
    evidence_search_response: Optional[Dict[str, Any]] = None
    search_policy: Optional[Dict[str, Any]] = None
    timestamp: str
    correlation_id: str
    execution_status: ValidationExecutionStatus
    error: Optional[str] = None
    error_details: Optional[ValidationErrorDetails] = None

    @model_validator(mode="after")
    def validate_execution_result(self):
        if self.execution_status == ValidationExecutionStatus.COMPLETED:
            if self.verdict is None:
                raise ValueError("COMPLETED validation requires verdict")
            if self.error is not None or self.error_details is not None:
                raise ValueError("COMPLETED validation cannot contain error data")
        else:
            if self.verdict is not None:
                raise ValueError("ERROR validation cannot contain verdict")
            if self.error_details is None:
                raise ValueError("ERROR validation requires error_details")
        return self


class LightValidationResponse(BaseModel):
    action: str = "light_validation_completed"
    order_id: str
    payload: LightValidationResponsePayload

class ValidatorAPIResponse(BaseModel):
    resultado: str
    descripcion: str
    confidence: Optional[str] = None
    sources: Optional[List[Dict[str, Any]]] = None
    evidence_used: Optional[List[Dict[str, Any]]] = None

# ============================================================
# 🔹 CONSISTENCY MODELS
# ============================================================
class ConsistencyCheckResult(BaseModel):
    """Modelo para un resultado de prueba de consistencia."""
    test: str
    toCompare: Optional[str | int | float] = None
    compared: Optional[str | int | float] = None
    result: str # "OK", "KO", o "SKIP"
    details: Optional[str] = None # Para añadir información de error si es KO
    
    
# ============================================================
# 🔹 EXTRACT FROM URL
# ============================================================    
    
# Modelo Pydantic para la request
class ExtractTextRequest(BaseModel):
    url: HttpUrl  # Valida que sea una URL válida

# Modelo Pydantic para la response
class ExtractedTextResponse(BaseModel):
    url: str
    title: str
    text: str
