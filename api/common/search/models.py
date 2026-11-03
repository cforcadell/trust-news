from typing import Any

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str
    max_results: int = Field(default=5, ge=1, le=50)
    include_domains: list[str] = Field(default_factory=list)
    external_source_policy: str = "none"
    search_profile: str = "primary"
    search_mode: str | None = None
    search_type: str | None = None


class SearchResult(BaseModel):
    url: str
    title: str = ""
    content: str = ""
    score: float | None = None
    raw_content: str | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractResult(BaseModel):
    """One requested URL, independently of the HTTP status of the API call."""

    requested_url: str
    status: str
    text: str = ""
    resolved_url: str | None = None
    freshness_status: str = "UNKNOWN"
    request_id: str | None = None
    cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    error: str | None = None
