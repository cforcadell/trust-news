from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from common.models.async_models import EvidencePreferredDomainsMode
from common.models.protocol_models import EnrichedAssertion



class EvidenceSearchPolicy(BaseModel):
    mode: str = "official_first"
    use_preferred_domains: EvidencePreferredDomainsMode = EvidencePreferredDomainsMode.NONE
    preferred_profile_id: str = "default"
    max_domains: int = Field(default=8, ge=1, le=50)
    max_results: int = Field(default=10, ge=1, le=50)
    max_queries_per_domain: int = Field(default=2, ge=1, le=10)
    fallback_to_general_search: bool = True


class EvidenceSelectionPolicy(BaseModel):
    max_domains: int = Field(default=8, ge=1, le=50)
    min_score: float = Field(default=0.35, ge=0.0)
    fallback_to_general_search: bool = True
    max_queries_per_domain: int = Field(default=2, ge=1, le=10)
    max_results: int = Field(default=5, ge=1, le=50)
    official_source_required_for_claim_types: List[str] = Field(default_factory=list)


class EvidenceScoringWeights(BaseModel):
    base_domain_score: float = Field(default=0.45, ge=0.0)
    category_match: float = Field(default=0.15, ge=0.0)
    subcategory_match: float = Field(default=0.12, ge=0.0)
    location_match: float = Field(default=0.12, ge=0.0)
    source_type_match: float = Field(default=0.10, ge=0.0)
    entity_match: float = Field(default=0.08, ge=0.0)
    official_bonus: float = Field(default=0.08, ge=0.0)
    statistics_bonus: float = Field(default=0.06, ge=0.0)
    global_location_bonus: float = Field(default=0.02, ge=0.0)


class EvidenceDomainProfile(BaseModel):
    profile_id: str
    profile_name: str
    enabled: bool = True
    version: int | str = 1
    description: str = ""
    normalization_versions: dict[str, int | str] = Field(default_factory=dict)
    selection_policy: EvidenceSelectionPolicy = Field(default_factory=EvidenceSelectionPolicy)
    scoring_weights: EvidenceScoringWeights = Field(default_factory=EvidenceScoringWeights)
    domains: List[dict] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class EvidenceNormalizationConfig(BaseModel):
    config_type: Literal["subcategories", "location_types", "source_types"]
    version: int | str = 1
    enabled: bool = True
    items: List[dict] = Field(default_factory=list)
    scopes: List[dict] = Field(default_factory=list)
    organizations: List[dict] = Field(default_factory=list)


class EvidenceSearchRequestV2(BaseModel):
    schema_version: str
    assertion: EnrichedAssertion
    search_policy: EvidenceSearchPolicy = Field(default_factory=EvidenceSearchPolicy)

    def model_post_init(self, __context):
        if self.schema_version != "evidence-search-request-v2":
            raise ValueError("Invalid evidence search request schema_version: expected evidence-search-request-v2")


class PreferredDomainResolution(BaseModel):
    domain: str
    source_type: str
    weight: float
    trust_score: float
    reason: str
    matched_profiles: List[str] = Field(default_factory=list)


class EvidenceSearchResponseV2(BaseModel):
    schema_version: str = "evidence-search-response-v2"
    assertion_id: str | int
    domain_resolution: dict
    queries_executed: List[str] = Field(default_factory=list)
    evidences: List[dict] = Field(default_factory=list)
