from typing import Any

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str
    max_results: int = Field(default=5, ge=1, le=50)
    include_domains: list[str] = Field(default_factory=list)
    external_source_policy: str = "none"


class SearchResult(BaseModel):
    url: str
    title: str = ""
    content: str = ""
    score: float | None = None
    raw_content: str | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
