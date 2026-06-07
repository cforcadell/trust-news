from typing import List

from pydantic import BaseModel, Field



class EvidenceSearchPolicy(BaseModel):
    mode: str = "official_first"
    use_preferred_domains: bool = False
    preferred_profile_id: str = "default"
    max_domains: int = Field(default=8, ge=1, le=50)
    max_results: int = Field(default=10, ge=1, le=50)
    max_queries_per_domain: int = Field(default=2, ge=1, le=10)
    fallback_to_general_search: bool = True


class EvidenceSearchRequestV2(BaseModel):
    schema_version: str
    assertion: dict
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
