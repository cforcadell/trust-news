from typing import List

from typing import Literal

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
