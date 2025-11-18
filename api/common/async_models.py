from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional, Dict, Any
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
# 🔹 GENERATE ASSERTIONS
# ============================================================

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


class ValidationWorkerTask(BaseModel):
    """Model for an incoming validation request, often for an internal worker/queue."""
    order_id: str
    postId: str # Changed from int to str for consistency
    idAssertion: str # Changed from int to str for consistency
    text: str
    context: Optional[str] = None
    idValidator: str


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
    order_id: str
    payload: ValidationCompletedPayload


class ValidationFailedPayload(BaseModel):
    """Model for a failed validation response."""
    order_id: str
    error_message: str
    error_type: str = "ProcessingError"
    # Re-adding validator/assertion IDs for full context
    postId: Optional[str] = None
    idValidator: Optional[str] = None
    idAssertion: Optional[str] = None


class ValidationFailedResponse(BaseModel):
    action: str = "validation_failed"
    order_id: str
    payload: ValidationFailedPayload
    
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