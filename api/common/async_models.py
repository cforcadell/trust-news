from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional, Dict, Any
from enum import IntEnum
from common.veredicto import Validacion


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
    """Represents a single assertion extracted from text."""
    idAssertion: str
    text: str
    categoryId: int


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
    categories: Optional[List[int]] = None
    

    
class AsyncMessage(BaseModel):
    action: str
    order_id: str



# ============================================================
# 🔹 VALIDATOR CONFIG MODELS
# ============================================================
class ValidatorType(IntEnum):
    General_AI = 1
    Trained_AI = 2
    Dedicated_Agent = 3
    Human = 4


class ValidatorStatus(IntEnum):
    Registered = 1
    Unregistered = 2
    Banned = 3


class ValidatorConfig(BaseModel):
    name: str
    type: ValidatorType = ValidatorType.General_AI
    provider: str
    model: str
    active_date: str
    updated_date: str
    end_date: Optional[str] = None
    status: ValidatorStatus = ValidatorStatus.Registered


class ValidatorConfigOnChain(BaseModel):
    validator: str
    ipfs_hash: str
    config: Optional[ValidatorConfig] = None


class ValidatorConfigEventPayload(BaseModel):
    validator: str
    ipfs_hash: str
    config: Optional[ValidatorConfig] = None


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


class GenerateAssertionsPayload(BaseModel):
    text: str


class GenerateAssertionsRequest(BaseModel):
    action: str = "generate_assertions"
    order_id: str
    payload: GenerateAssertionsPayload


class AssertionGeneratedPayload(BaseModel):
    text: str
    assertions: List[Assertion]
    publisher: str


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
    
class PreGeneratedAssertion(BaseModel):
    idAssertion: str
    text: str
    categoryId: int

class PublishWithAssertionsRequest(BaseModel):
    text: str
    assertions: List[PreGeneratedAssertion]

# ============================================================
# 🔹 UPLOAD IPFS
# ============================================================

class UploadIpfsPayload(BaseModel):
    document: Document


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


class RequestValidationRequest(BaseModel):
    action: str = "request_validation"
    order_id: str
    payload: RequestValidationPayload




# ============================================================
# 🔹 VALIDATION COMPLETED/FAILED
# ============================================================

class ValidationCompletedPayload(BaseModel):
    """Model for a successful validation response."""
    postId: str
    idValidator: str
    idAssertion: str
    approval: Validacion
    text: str
    tx_hash: str
    validator_alias: str


class ValidationCompletedResponse(BaseModel):
    action: str = "validation_completed"
    order_id: str = ""  # Optional - news-chain may not have order_id, only postId
    payload: ValidationCompletedPayload


    
class ValidatorAPIResponse(BaseModel):
    resultado: str
    descripcion: str

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
