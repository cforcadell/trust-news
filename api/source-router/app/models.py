from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from common.models.protocol_models import JurisdictionContext
from common.search.normalization import normalize_domain
from common.routing_taxonomy import (
    TAXONOMY_VERSION,
    AuthorityLevel,
    EvidenceKind,
    MatchLevel,
    SourceType,
    TopicCode,
)


class ResolveRouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic_code: TopicCode
    evidence_kind: EvidenceKind
    jurisdiction: JurisdictionContext
    language: str = "unknown"

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        normalized = str(value or "unknown").strip().lower()
        return normalized[:8] or "unknown"


class RouteSignature(BaseModel):
    model_config = ConfigDict(extra="forbid")
    taxonomy_version: Literal["routing-taxonomy-v1"] = TAXONOMY_VERSION
    topic_code: TopicCode
    evidence_kind: EvidenceKind
    jurisdiction: JurisdictionContext
    jurisdiction_key: str


class CandidateSource(BaseModel):
    domain: str
    url: str
    title: str = ""
    snippet: str = ""
    provider_score: float | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("domain", mode="before")
    @classmethod
    def normalize_candidate_domain(cls, value: str) -> str:
        domain = normalize_domain(value)
        if not domain:
            raise ValueError("candidate domain is required")
        return domain


class SourceClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: str
    source_type: SourceType = SourceType.UNKNOWN
    authority_level: AuthorityLevel = AuthorityLevel.UNKNOWN
    jurisdictions: list[JurisdictionContext] = Field(default_factory=list)
    topic_codes: list[TopicCode] = Field(default_factory=list)
    evidence_kinds: list[EvidenceKind] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    topic_match: MatchLevel = MatchLevel.UNKNOWN
    evidence_kind_match: MatchLevel = MatchLevel.UNKNOWN
    semantic_relevance: float = Field(default=0, ge=0, le=1)
    classification_confidence: float = Field(default=0, ge=0, le=1)
    reason: str = ""
    provider_score: float | None = None

    @field_validator("domain", mode="before")
    @classmethod
    def normalize_classified_domain(cls, value: str) -> str:
        domain = normalize_domain(value)
        if not domain:
            raise ValueError("classified domain is required")
        return domain

    @field_validator("authority_level", mode="before")
    @classmethod
    def normalize_authority_level(cls, value: Any) -> Any:
        if isinstance(value, AuthorityLevel):
            return value
        normalized = str(value or "").strip().upper()
        aliases = {
            "LOCAL": AuthorityLevel.LOCAL_PRIMARY,
            "REGIONAL": AuthorityLevel.REGIONAL_PRIMARY,
            "NATIONAL": AuthorityLevel.NATIONAL_PRIMARY,
            "SUPRANATIONAL": AuthorityLevel.SUPRANATIONAL_PRIMARY,
            "INTERNATIONAL": AuthorityLevel.INTERNATIONAL_PRIMARY,
            "GLOBAL": AuthorityLevel.GLOBAL_PRIMARY,
            "SECONDARY": AuthorityLevel.SECONDARY_AUTHORITATIVE,
        }
        return aliases.get(normalized, normalized)

    @field_validator("languages")
    @classmethod
    def normalize_languages(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(str(value).strip().lower()[:8] for value in values if str(value).strip()))


class ClassificationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classifications: list[SourceClassification]


class DomainProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: str
    source_type: SourceType
    authority_level: AuthorityLevel
    jurisdictions: list[JurisdictionContext]
    topic_codes: list[TopicCode]
    evidence_kinds: list[EvidenceKind]
    languages: list[str]
    classification_confidence: float = Field(ge=0, le=1)
    reason: str
    taxonomy_version: Literal["routing-taxonomy-v1"] = TAXONOMY_VERSION
    profile_version: str
    classification_model: str
    created_at: datetime
    updated_at: datetime
    last_verified_at: datetime

    @field_validator("domain", mode="before")
    @classmethod
    def normalize_profile_domain(cls, value: str) -> str:
        domain = normalize_domain(value)
        if not domain:
            raise ValueError("profile domain is required")
        return domain


class RouteCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: str
    topic_match: MatchLevel
    evidence_kind_match: MatchLevel
    semantic_relevance: float = Field(ge=0, le=1)
    provider_score: float | None = None
    reason: str
    base_score: float = Field(ge=0, le=1)


class RoutedSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: str
    source_type: SourceType
    authority_level: AuthorityLevel
    jurisdictions: list[JurisdictionContext]
    topic_codes: list[TopicCode]
    evidence_kinds: list[EvidenceKind]
    languages: list[str]
    route_score: float = Field(ge=0, le=1)
    rank: int = Field(ge=1)
    reason: str
    profile_version: str


RouteDiagnosticCode = Literal[
    "CLASSIFICATION_FAILED", "CLASSIFICATION_PARTIAL", "PROFILE_FALLBACK",
    "NO_DISCOVERY_CANDIDATES", "NO_ELIGIBLE_SOURCES",
]


class RouteDiagnostics(BaseModel):
    discovered_domains: list[str] = Field(default_factory=list)
    classified_domains: list[str] = Field(default_factory=list)
    rejected_domains: list[str] = Field(default_factory=list)
    failed_domains: list[str] = Field(default_factory=list)
    fallback_domains: list[str] = Field(default_factory=list)


class RouteDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    route_key: str
    route_signature: RouteSignature
    candidates: list[RouteCandidate] = Field(default_factory=list)
    router_version: str
    discovery_provider: str
    classification_model: str
    created_at: datetime
    updated_at: datetime
    last_refreshed_at: datetime
    refresh_after: datetime
    degraded: bool = False
    diagnostic_code: RouteDiagnosticCode | None = None
    diagnostics: RouteDiagnostics = Field(default_factory=RouteDiagnostics)


class ResolveRouteResponse(BaseModel):
    route_key: str
    route_state: Literal["FRESH", "MISSING", "STALE"]
    sources: list[RoutedSource] = Field(default_factory=list)
    router_version: str
    taxonomy_version: Literal["routing-taxonomy-v1"] = TAXONOMY_VERSION
    stale_route_used: bool = False
    degraded: bool = False
    diagnostic_code: RouteDiagnosticCode | None = None
    diagnostics: RouteDiagnostics = Field(default_factory=RouteDiagnostics)


class StoredRouteResponse(RouteDocument):
    route_state: Literal["FRESH", "STALE"]
