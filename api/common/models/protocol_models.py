from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from common.category_catalog import CATEGORY_CATALOG_PROMPT, CATEGORY_IDS, validate_category_id
from common.search.normalization import normalize_domain
from common.routing_taxonomy import (
    EVIDENCE_KIND_PROMPT,
    TAXONOMY_VERSION,
    TOPIC_PROMPT,
    EntityRole,
    EntityType,
    EvidenceKind,
    JurisdictionScope,
    TemporalType,
    TopicCode,
    validate_topic_category,
)


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


CategoryId = Annotated[
    StrictInt,
    Field(json_schema_extra={"enum": sorted(CATEGORY_IDS)}),
    AfterValidator(validate_category_id),
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clamp_confidence(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = default
    return max(0.0, min(1.0, parsed))


class JurisdictionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: JurisdictionScope
    country_code: Optional[str] = Field(default=None, pattern=r"^[A-Z]{2}$")
    region_code: Optional[str] = Field(default=None, pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$")
    jurisdiction_code: Optional[str] = Field(default=None, pattern=r"^[A-Z][A-Z0-9._-]{1,31}$")
    applicable_country_codes: List[str] = Field(default_factory=list)

    @field_validator("country_code", "region_code", "jurisdiction_code", mode="before")
    @classmethod
    def upper_codes(cls, value: Any) -> Any:
        return str(value).strip().upper() if value else None

    @field_validator("applicable_country_codes", mode="before")
    @classmethod
    def normalize_applicable_countries(cls, values: Any) -> List[str]:
        normalized = list(dict.fromkeys(str(value).strip().upper() for value in (values or []) if str(value).strip()))
        if any(not re.fullmatch(r"[A-Z]{2}", value) for value in normalized):
            raise ValueError("applicable_country_codes must contain ISO 3166-1 alpha-2 codes")
        return normalized

    @model_validator(mode="after")
    def validate_codes_for_scope(self):
        if self.scope in {JurisdictionScope.GLOBAL, JurisdictionScope.UNKNOWN}:
            if self.country_code or self.region_code or self.jurisdiction_code or self.applicable_country_codes:
                raise ValueError(f"{self.scope.value} jurisdiction cannot contain codes")
        elif self.scope == JurisdictionScope.SUPRANATIONAL:
            if not self.jurisdiction_code or self.country_code or self.region_code:
                raise ValueError("SUPRANATIONAL jurisdiction requires only jurisdiction_code")
        elif self.scope == JurisdictionScope.COUNTRY:
            if not self.country_code or self.region_code or self.jurisdiction_code or self.applicable_country_codes:
                raise ValueError("COUNTRY jurisdiction requires country_code and no region_code")
        elif self.scope == JurisdictionScope.REGION:
            if not self.country_code or not self.region_code or self.jurisdiction_code or self.applicable_country_codes:
                raise ValueError("REGION jurisdiction requires country_code and region_code")
        elif self.scope == JurisdictionScope.LOCAL:
            if not self.country_code or not self.region_code or not self.jurisdiction_code or self.applicable_country_codes:
                raise ValueError("LOCAL jurisdiction requires country_code, region_code and jurisdiction_code")
        return self

    def routing_key(self) -> str:
        return ":".join(filter(None, (self.scope.value, self.jurisdiction_code, self.country_code, self.region_code)))


class LocationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "unknown"
    scope: JurisdictionScope = JurisdictionScope.UNKNOWN
    country_code: Optional[str] = None
    region_code: Optional[str] = None
    origin: Origin = Origin.UNKNOWN
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("country_code", "region_code", mode="before")
    @classmethod
    def upper_location_codes(cls, value: Any) -> Any:
        return str(value).strip().upper() if value else None


class EntityContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "unknown"
    type: EntityType = EntityType.UNKNOWN
    role: EntityRole = EntityRole.UNKNOWN
    origin: Origin = Origin.UNKNOWN
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class TemporalContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = "unknown"
    type: TemporalType = TemporalType.UNKNOWN
    origin: Origin = Origin.UNKNOWN
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class AssertionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locations: List[LocationContext] = Field(default_factory=list)
    entities: List[EntityContext] = Field(default_factory=list)
    temporal_context: List[TemporalContext] = Field(default_factory=list)
    language: str = "unknown"
    jurisdiction: JurisdictionContext

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        value = (value or "unknown").strip().lower()
        return value[:8] if value else "unknown"


class SearchHints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    search_keywords: List[str] = Field(default_factory=list)
    suggested_queries: List[str] = Field(default_factory=list)


class ContextConfidence(BaseModel):
    location: float = Field(default=0.0, ge=0.0, le=1.0)
    entities: float = Field(default=0.0, ge=0.0, le=1.0)
    temporal: float = Field(default=0.0, ge=0.0, le=1.0)


class EnrichedAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assertion_id: int | str
    assertion_index: int = Field(ge=0)
    text: str
    categoryId: CategoryId
    topic_code: TopicCode
    evidence_kind: EvidenceKind
    taxonomy_version: Literal["routing-taxonomy-v1"] = TAXONOMY_VERSION
    context: AssertionContext
    search_hints: SearchHints = Field(default_factory=SearchHints)
    context_confidence: ContextConfidence = Field(default_factory=ContextConfidence)

    @model_validator(mode="after")
    def validate_topic_for_category(self):
        validate_topic_category(self.topic_code, self.categoryId)
        return self

    def to_chain_assertion(self) -> Dict[str, Any]:
        return {
            "idAssertion": str(self.assertion_id),
            "text": self.text,
            "categoryId": self.categoryId,
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

    @field_validator("source_domain", mode="before")
    @classmethod
    def normalize_source_domain(cls, value: Any) -> Optional[str]:
        normalized = normalize_domain(value)
        return normalized or None


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
        if data.get("schema_version") != ASSERTIONS_DOCUMENT_SCHEMA_VERSION:
            raise ValueError("Invalid assertions document schema_version: expected assertions-document-v2")
        if "order_id" in data:
            raise ValueError("order_id is operational and must not be part of assertions-document-v2")
        return data

    @model_validator(mode="after")
    def validate_assertion_order(self):
        for index, assertion in enumerate(self.assertions):
            if assertion.assertion_index != index or str(assertion.assertion_id) != str(index + 1):
                raise ValueError("assertions must use contiguous assertion_id and assertion_index values")
        return self

    def to_chain_assertions(self) -> List[Dict[str, Any]]:
        return [assertion.to_chain_assertion() for assertion in self.assertions]


class Correlation(BaseModel):
    order_id: Optional[str] = None


class SourceDocument(BaseModel):
    storage: SourceDocumentStorage
    cid: Optional[str] = None
    schema_version: Literal["assertions-document-v2"] = ASSERTIONS_DOCUMENT_SCHEMA_VERSION


class OriginDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: Optional[str] = None
    domain: Optional[str] = None

    @field_validator("domain", mode="before")
    @classmethod
    def normalize_origin_domain(cls, value: Any) -> Optional[str]:
        normalized = normalize_domain(value)
        return normalized or None


class AssertionValidationPayloadV2(BaseModel):
    schema_version: Literal["assertion-validation-payload-v2"] = ASSERTION_VALIDATION_PAYLOAD_SCHEMA_VERSION
    mode: ValidationMode
    post_id: Optional[int | str] = None
    correlation: Correlation = Field(default_factory=Correlation)
    assertion: EnrichedAssertion
    source_document: SourceDocument
    origin_document: OriginDocument

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("schema_version") != ASSERTION_VALIDATION_PAYLOAD_SCHEMA_VERSION:
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
    source_url: Optional[str] = None,
    source_domain: Optional[str] = None,
) -> AssertionsDocumentV2:
    parsed_mode = parse_validation_mode(mode)
    enriched = []
    for index, assertion in enumerate(assertions):
        parsed = assertion if isinstance(assertion, EnrichedAssertion) else EnrichedAssertion(**assertion_input_for_protocol(assertion))
        enriched.append(parsed.model_copy(update={"assertion_id": index + 1, "assertion_index": index}))
    return AssertionsDocumentV2(
        schema_version=ASSERTIONS_DOCUMENT_SCHEMA_VERSION,
        mode=parsed_mode,
        network=NetworkRef(**network) if network else None,
        post=ProtocolPost(
            post_id=post_id,
            original_text=text,
            source_url=source_url,
            source_domain=source_domain,
            language=_first_language(enriched),
        ),
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
    origin_url: Optional[str] = None,
    origin_domain: Optional[str] = None,
) -> AssertionValidationPayloadV2:
    parsed_mode = parse_validation_mode(mode)
    parsed_storage = storage if isinstance(storage, SourceDocumentStorage) else SourceDocumentStorage(str(storage).lower())
    parsed_assertion = assertion if isinstance(assertion, EnrichedAssertion) else EnrichedAssertion(**assertion_input_for_protocol(assertion))
    return AssertionValidationPayloadV2(
        schema_version=ASSERTION_VALIDATION_PAYLOAD_SCHEMA_VERSION,
        mode=parsed_mode,
        post_id=post_id,
        correlation=Correlation(order_id=order_id),
        assertion=parsed_assertion,
        source_document=SourceDocument(storage=parsed_storage, cid=cid),
        origin_document=OriginDocument(url=origin_url, domain=origin_domain),
    )


def _first_language(assertions: List[EnrichedAssertion]) -> str:
    for assertion in assertions:
        language = assertion.context.language
        if language and language != "unknown":
            return language
    return "unknown"
