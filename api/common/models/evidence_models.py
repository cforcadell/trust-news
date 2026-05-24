from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class EvidenceSearchRequest(BaseModel):
    order_id: Optional[str] = None
    assertion_id: Optional[str | int] = None
    assertion_text: str
    category: Optional[str] = None
    language: Optional[str] = None
    temporal_context: Optional[str] = None
    location_context: Optional[str] = None
    max_sources: int = Field(default=5, ge=1, le=10)
    force_refresh: bool = False


class EvidenceSearchConfigBase(BaseModel):
    category_id: Optional[int] = Field(None, description="Categoria de asercion. Null o config_id=default aplica como base global.")
    category_name: Optional[str] = Field(None, description="Nombre legible de la categoria")
    preferred_domains: List[str] = Field(default_factory=list, description="Dominios preferentes para buscar primero")
    official_domains: List[str] = Field(default_factory=list, description="Alias compatible: dominios considerados oficiales")
    query_terms: List[str] = Field(default_factory=list, description="Terminos extra para orientar la query")
    official_first: bool = True
    enabled: bool = True


class EvidenceSearchConfigUpsert(EvidenceSearchConfigBase):
    pass


class EvidenceSearchConfigResponse(EvidenceSearchConfigBase):
    config_id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
