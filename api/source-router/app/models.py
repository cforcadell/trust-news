from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RouteLocation(BaseModel):
    name: str = "unknown"
    country_code: str | None = None
    region_code: str | None = None
    scope: str = "unknown"

    @field_validator("country_code", "region_code")
    @classmethod
    def upper_codes(cls, value: str | None) -> str | None:
        return str(value).strip().upper() if value else None


class RouteEntity(BaseModel):
    name: str
    type: str = "unknown"


class ResolveRouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str | int = "unknown"
    subcategory: str = "unknown"
    claim_type: str = "general"
    location: RouteLocation = Field(default_factory=RouteLocation)
    entities: list[RouteEntity] = Field(default_factory=list)
    language: str = "unknown"


class RouteSignature(BaseModel):
    claim_type: str
    subcategory: str
    country_code: str = "GLOBAL"
    region_code: str = "*"


class CandidateSource(BaseModel):
    domain: str
    url: str
    title: str = ""
    snippet: str = ""
    provider_score: float | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class JurisdictionClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str = "unknown"
    country_code: str | None = None
    region_code: str | None = None
    applicable_country_codes: list[str] = Field(default_factory=list)

    @field_validator("country_code", "region_code")
    @classmethod
    def upper_codes(cls, value: str | None) -> str | None:
        return str(value).strip().upper() if value else None

    @field_validator("applicable_country_codes")
    @classmethod
    def upper_applicable_codes(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(str(value).strip().upper() for value in values if str(value).strip()))


class SourceClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str
    source_type: str = "unknown"
    authority_level: str = "unknown"
    jurisdiction: JurisdictionClassification = Field(default_factory=JurisdictionClassification)
    claim_type_match: Literal["exact", "partial", "none", "unknown"] = "unknown"
    subcategory_match: Literal["exact", "partial", "none", "unknown"] = "unknown"
    entity_match: Literal["exact", "partial", "none", "unknown"] = "unknown"
    language_match: Literal["exact", "partial", "none", "unknown"] = "unknown"
    semantic_relevance: float = Field(default=0, ge=0, le=1)
    classification_confidence: float = Field(default=0, ge=0, le=1)
    reason: str = ""
    provider_score: float | None = None


class ClassificationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classifications: list[SourceClassification]


class RoutedSource(SourceClassification):
    rank: int
    routing_score: float = Field(ge=0, le=1)


class RouteDocument(BaseModel):
    route_key: str
    route_signature: RouteSignature
    category: str | int = "unknown"
    entities: list[str] = Field(default_factory=list)
    sources: list[RoutedSource] = Field(default_factory=list)
    router_version: str
    discovery_provider: str
    classification_model: str
    created_at: datetime
    updated_at: datetime
    last_refreshed_at: datetime
    refresh_after: datetime


class ResolveRouteResponse(BaseModel):
    route_key: str
    route_state: Literal["FRESH", "MISSING", "STALE"]
    sources: list[RoutedSource] = Field(default_factory=list)
    router_version: str
    stale_route_used: bool = False


class StoredRouteResponse(RouteDocument):
    route_state: Literal["FRESH", "STALE"]
