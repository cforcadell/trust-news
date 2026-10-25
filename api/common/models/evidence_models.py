from typing import Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from common.models.async_models import EvidenceSearchStrategy
from common.models.protocol_models import EnrichedAssertion, JurisdictionContext, OriginDocument
from common.routing_taxonomy import AuthorityLevel, EvidenceKind, SourceType, TopicCode
from common.search.normalization import normalize_domain


class PreferredSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str
    source_type: SourceType
    authority_level: AuthorityLevel
    jurisdictions: List[JurisdictionContext] = Field(default_factory=list)
    topic_codes: List[TopicCode]
    evidence_kinds: List[EvidenceKind]
    languages: List[str]
    route_score: float = Field(ge=0, le=1)
    rank: int = Field(ge=1)
    reason: str
    profile_version: str

    @field_validator("domain", mode="before")
    @classmethod
    def normalize_source_domain(cls, value: str) -> str:
        domain = normalize_domain(value)
        if not domain:
            raise ValueError("preferred source domain is required")
        return domain

    @field_validator("languages")
    @classmethod
    def normalize_source_languages(cls, values: List[str]) -> List[str]:
        return list(dict.fromkeys(str(value).strip().lower()[:8] for value in values if str(value).strip()))


class EvidenceSearchPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: EvidenceSearchStrategy
    max_domains: int = Field(default=8, ge=1, le=50)
    max_results: int = Field(default=10, ge=1, le=50)
    max_queries: int = Field(default=2, ge=1, le=10)
    preferred_sources: List[PreferredSource] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_strategy_sources(self):
        if self.strategy == EvidenceSearchStrategy.LOCAL and not self.preferred_sources:
            raise ValueError("LOCAL strategy requires preferred_sources from Source Router")
        if self.strategy != EvidenceSearchStrategy.LOCAL and self.preferred_sources:
            raise ValueError("External strategies cannot receive preferred_sources")
        return self


class EvidenceSearchRequestV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["evidence-search-request-v2"]
    assertion: EnrichedAssertion
    origin_document: OriginDocument
    search_policy: EvidenceSearchPolicy


class EvidenceRetrievalSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_documents: int = Field(ge=0)
    candidates_considered: int = Field(ge=0)
    fetch_attempts: int = Field(ge=0)
    http_requests: int = Field(default=0, ge=0)
    http_responses: int = Field(default=0, ge=0)
    http_successes: int = Field(default=0, ge=0)
    documents_scheduled: int = Field(ge=0)
    documents_attempted: int = Field(default=0, ge=0)
    documents_extracted: int = Field(ge=0)
    documents_citable: int = Field(ge=0)
    outcome_counts: Dict[str, int] = Field(default_factory=dict)
    retry_actions: int = Field(default=0, ge=0)
    retry_recovered: int = Field(default=0, ge=0)
    retry_exhausted: int = Field(default=0, ge=0)
    candidate_substitutions: int = Field(default=0, ge=0)
    substitution_recovered: int = Field(default=0, ge=0)
    substitution_exhausted: int = Field(default=0, ge=0)
    fallback_rounds: int = Field(ge=0)
    failure_counts: Dict[str, int] = Field(default_factory=dict)
    negative_history_hits: int = Field(default=0, ge=0)
    negative_history_attempts_avoided: int = Field(default=0, ge=0)
    stop_reason: Literal["TARGET_REACHED", "BUDGET_EXHAUSTED"]


class EvidenceCachePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classification: Literal["POSITIVE", "TRANSIENT_NEGATIVE", "UNUSABLE_NEGATIVE"]
    ttl_seconds: int = Field(ge=0)


class EvidenceSearchResponseV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["evidence-search-response-v2"] = "evidence-search-response-v2"
    assertion_id: str | int
    domain_resolution: dict
    search_policy: EvidenceSearchPolicy
    queries_executed: List[dict] = Field(default_factory=list)
    evidences: List[dict] = Field(default_factory=list)
    cached: bool
    cache_key: str
    evidence_bundle_hash: str | None = None
    provider_trace: dict | None = None
    evaluation_trace: dict | None = None
    retrieval_summary: EvidenceRetrievalSummary | None = None
    cache_policy: EvidenceCachePolicy | None = None
