from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
import unicodedata

from pydantic import BaseModel, Field, field_validator, model_validator


ASSERTIONS_DOCUMENT_SCHEMA_VERSION = "assertions-document-v2"
ASSERTION_VALIDATION_PAYLOAD_SCHEMA_VERSION = "assertion-validation-payload-v2"
EVIDENCE_SEARCH_REQUEST_SCHEMA_VERSION = "evidence-search-request-v2"
EVIDENCE_SEARCH_RESPONSE_SCHEMA_VERSION = "evidence-search-response-v2"


class ValidationMode(str, Enum):
    BLOCKCHAIN = "BLOCKCHAIN"
    LIGHT = "LIGHT"


class SourceDocumentStorage(str, Enum):
    IPFS = "ipfs"
    INLINE = "inline"


class Origin(str, Enum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


JURISDICTIONS = {
    "local",
    "regional",
    "national",
    "european",
    "international",
    "corporate",
    "sports",
    "unknown",
}

SOURCE_TYPES = {
    "official",
    "public_registry",
    "statistics",
    "scientific",
    "academic",
    "international_organization",
    "reputable_media",
    "corporate",
    "sports_federation",
    "legal",
    "financial",
    "social_media",
    "unknown",
}


CHAIN_CATEGORIES: Dict[int, str] = {
    1: "ECONOMÍA",
    2: "DEPORTES",
    3: "POLÍTICA",
    4: "TECNOLOGÍA",
    5: "SALUD",
    6: "ENTRETENIMIENTO",
    7: "CIENCIA",
    8: "CULTURA",
    9: "MEDIO AMBIENTE",
    10: "SOCIAL",
}


def _category_key(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.replace("-", " ").replace("_", " ")


CATEGORY_ALIASES: Dict[str, int] = {
    _category_key(name): category_id for category_id, name in CHAIN_CATEGORIES.items()
}
CATEGORY_ALIASES.update({
    "ECONOMY": 1,
    "ECONOMIA": 1,
    "SPORT": 2,
    "SPORTS": 2,
    "DEPORTE": 2,
    "POLITICS": 3,
    "POLITICA": 3,
    "PUBLIC ADMINISTRATION": 3,
    "TECHNOLOGY": 4,
    "TECNOLOGIA": 4,
    "HEALTH": 5,
    "ENTERTAINMENT": 6,
    "SCIENCE": 7,
    "CULTURE": 8,
    "ENVIRONMENT": 9,
    "ENVIRONMENTAL": 9,
    "MEDIOAMBIENTE": 9,
    "SOCIAL": 10,
})

ACCEPTED_CATEGORY_PROMPT = "\n".join(f"{category_id} {name}" for category_id, name in CHAIN_CATEGORIES.items())


def category_id_for_value(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("Invalid category: booleans are not valid category ids")
    try:
        category_id = int(value)
    except Exception:
        category_id = CATEGORY_ALIASES.get(_category_key(value), 0)
    if category_id not in CHAIN_CATEGORIES:
        accepted = ", ".join(CHAIN_CATEGORIES.values())
        raise ValueError(f"Invalid category {value!r}. Accepted categories: {accepted}")
    return category_id


def canonical_category(value: Any) -> str:
    return CHAIN_CATEGORIES[category_id_for_value(value)]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clamp_confidence(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = default
    return max(0.0, min(1.0, parsed))


class LocationContext(BaseModel):
    name: str = "unknown"
    type: str = "unknown"
    country_code: Optional[str] = None
    region_code: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    origin: Origin = Origin.UNKNOWN
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class EntityContext(BaseModel):
    name: str = "unknown"
    type: str = "unknown"
    role: str = "unknown"
    origin: Origin = Origin.UNKNOWN
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class TemporalContext(BaseModel):
    value: str = "unknown"
    type: str = "unknown"
    origin: Origin = Origin.UNKNOWN
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class AssertionContext(BaseModel):
    locations: List[LocationContext] = Field(default_factory=list)
    entities: List[EntityContext] = Field(default_factory=list)
    temporal_context: List[TemporalContext] = Field(default_factory=list)
    language: str = "unknown"
    jurisdiction: str = "unknown"

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_context_lists(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        normalized = dict(data)

        def normalize_items(field: str, value_key: str) -> None:
            items = normalized.get(field)
            if items is None:
                return
            if not isinstance(items, list):
                items = [items]
            coerced = []
            for item in items:
                if isinstance(item, dict):
                    coerced.append(item)
                elif item is not None:
                    coerced.append({
                        value_key: str(item),
                        "origin": Origin.EXPLICIT,
                        "confidence": 0.5,
                    })
            normalized[field] = coerced

        normalize_items("locations", "name")
        normalize_items("entities", "name")
        normalize_items("temporal_context", "value")
        return normalized

    @field_validator("jurisdiction")
    @classmethod
    def normalize_jurisdiction(cls, value: str) -> str:
        normalized = (value or "unknown").strip().lower()
        return normalized if normalized in JURISDICTIONS else "unknown"

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        value = (value or "unknown").strip().lower()
        return value[:8] if value else "unknown"


class SearchHints(BaseModel):
    preferred_source_types: List[str] = Field(default_factory=list)
    search_keywords: List[str] = Field(default_factory=list)
    suggested_queries: List[str] = Field(default_factory=list)

    @field_validator("preferred_source_types")
    @classmethod
    def normalize_source_types(cls, values: List[str]) -> List[str]:
        normalized = []
        for value in values or []:
            item = str(value or "unknown").strip().lower()
            normalized.append(item if item in SOURCE_TYPES else "unknown")
        return list(dict.fromkeys(normalized))


class ContextConfidence(BaseModel):
    location: float = Field(default=0.0, ge=0.0, le=1.0)
    entities: float = Field(default=0.0, ge=0.0, le=1.0)
    temporal: float = Field(default=0.0, ge=0.0, le=1.0)


class EnrichedAssertion(BaseModel):
    assertion_id: int | str
    assertion_index: int = Field(ge=0)
    text: str
    category: str | int
    subcategory: str = "unknown"
    context: AssertionContext = Field(default_factory=AssertionContext)
    search_hints: SearchHints = Field(default_factory=SearchHints)
    context_confidence: ContextConfidence = Field(default_factory=ContextConfidence)

    @field_validator("category")
    @classmethod
    def normalize_category(cls, value: str | int) -> str:
        return canonical_category(value)

    def category_id_for_chain(self) -> int:
        return category_id_for_value(self.category)

    def to_chain_assertion(self) -> Dict[str, Any]:
        return {
            "idAssertion": str(self.assertion_id),
            "text": self.text,
            "categoryId": self.category_id_for_chain(),
        }


class NetworkRef(BaseModel):
    chain_id: Optional[int] = None
    contract_address: Optional[str] = None


class ProtocolPost(BaseModel):
    post_id: Optional[int | str] = None
    title: Optional[str] = None
    original_text: str
    source_url: Optional[str] = None
    source_domain: Optional[str] = None
    language: str = "unknown"
    published_at: Optional[str] = None
    submitted_at: str = Field(default_factory=utc_now_iso)


class GeneratorInfo(BaseModel):
    service: str = "generate-asertions"
    provider: str = "unknown"
    model: Optional[str] = None
    generated_at: str = Field(default_factory=utc_now_iso)


class AssertionsDocumentV2(BaseModel):
    schema_version: Literal["assertions-document-v2"] = ASSERTIONS_DOCUMENT_SCHEMA_VERSION
    protocol: str = "TrustNews"
    mode: ValidationMode = ValidationMode.BLOCKCHAIN
    network: Optional[NetworkRef] = None
    post: ProtocolPost
    generator: GeneratorInfo = Field(default_factory=GeneratorInfo)
    assertions: List[EnrichedAssertion]

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_or_operational_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        version = data.get("schema_version", ASSERTIONS_DOCUMENT_SCHEMA_VERSION)
        if version != ASSERTIONS_DOCUMENT_SCHEMA_VERSION:
            raise ValueError("Invalid assertions document schema_version: expected assertions-document-v2")
        if "order_id" in data:
            raise ValueError("order_id is operational and must not be part of assertions-document-v2")
        return data

    def to_chain_assertions(self) -> List[Dict[str, Any]]:
        return [assertion.to_chain_assertion() for assertion in self.assertions]


class Correlation(BaseModel):
    order_id: Optional[str] = None


class SourceDocument(BaseModel):
    storage: SourceDocumentStorage
    cid: Optional[str] = None
    schema_version: Literal["assertions-document-v2"] = ASSERTIONS_DOCUMENT_SCHEMA_VERSION


class AssertionValidationPayloadV2(BaseModel):
    schema_version: Literal["assertion-validation-payload-v2"] = ASSERTION_VALIDATION_PAYLOAD_SCHEMA_VERSION
    mode: ValidationMode
    post_id: Optional[int | str] = None
    correlation: Correlation = Field(default_factory=Correlation)
    assertion: EnrichedAssertion
    source_document: SourceDocument

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("schema_version", ASSERTION_VALIDATION_PAYLOAD_SCHEMA_VERSION) != ASSERTION_VALIDATION_PAYLOAD_SCHEMA_VERSION:
            raise ValueError("Invalid validation payload schema_version: expected assertion-validation-payload-v2")
        return data


def parse_validation_mode(value: Any) -> ValidationMode:
    if isinstance(value, ValidationMode):
        return value
    raw = getattr(value, "value", value)
    return ValidationMode(str(raw).upper())


def assertion_input_for_protocol(assertion: Any) -> EnrichedAssertion | Dict[str, Any]:
    if isinstance(assertion, EnrichedAssertion):
        return assertion
    raw = assertion.model_dump() if hasattr(assertion, "model_dump") else dict(assertion)
    if "idAssertion" in raw:
        raw["assertion_id"] = raw.pop("idAssertion")
        raw["assertion_index"] = int(raw["assertion_id"]) - 1
    if "category" not in raw and "categoryId" in raw:
        raw["category"] = raw["categoryId"]
    return raw


def build_assertions_document_v2(
    *,
    text: str,
    assertions: List[Any],
    mode: ValidationMode | str,
    provider: str = "unknown",
    model: Optional[str] = None,
    post_id: Optional[int | str] = None,
    network: Optional[Dict[str, Any]] = None,
) -> AssertionsDocumentV2:
    parsed_mode = parse_validation_mode(mode)
    enriched = [a if isinstance(a, EnrichedAssertion) else EnrichedAssertion(**assertion_input_for_protocol(a)) for a in assertions]
    return AssertionsDocumentV2(
        mode=parsed_mode,
        network=NetworkRef(**network) if network else None,
        post=ProtocolPost(post_id=post_id, original_text=text, language=_first_language(enriched)),
        generator=GeneratorInfo(provider=provider, model=model),
        assertions=enriched,
    )


def build_assertion_validation_payload_v2(
    *,
    mode: ValidationMode | str,
    assertion: EnrichedAssertion | Dict[str, Any],
    storage: SourceDocumentStorage | str,
    post_id: Optional[int | str] = None,
    cid: Optional[str] = None,
    order_id: Optional[str] = None,
) -> AssertionValidationPayloadV2:
    parsed_mode = parse_validation_mode(mode)
    parsed_storage = storage if isinstance(storage, SourceDocumentStorage) else SourceDocumentStorage(str(storage).lower())
    parsed_assertion = assertion if isinstance(assertion, EnrichedAssertion) else EnrichedAssertion(**assertion_input_for_protocol(assertion))
    return AssertionValidationPayloadV2(
        mode=parsed_mode,
        post_id=post_id,
        correlation=Correlation(order_id=order_id),
        assertion=parsed_assertion,
        source_document=SourceDocument(storage=parsed_storage, cid=cid),
    )


def _first_language(assertions: List[EnrichedAssertion]) -> str:
    for assertion in assertions:
        language = assertion.context.language
        if language and language != "unknown":
            return language
    return "unknown"
