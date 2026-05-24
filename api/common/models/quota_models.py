from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ClientStatus(str, Enum):
    ALTA = "Active"
    BAJA = "Deactivated"
    SUSPENDIDO = "Suspended"


class QuotaDetail(BaseModel):
    news_generation: int = 0
    blockchain_validation: int = 0


class ClientBase(BaseModel):
    name: Optional[str] = Field(None, description="Nombre legible del cliente")
    limits: QuotaDetail = Field(default_factory=QuotaDetail, description="Límite máximo permitido")
    consumed: QuotaDetail = Field(default_factory=QuotaDetail, description="Cantidad ya consumida")
    status: ClientStatus = Field(default=ClientStatus.ALTA, description="Estado operativo del cliente")
    active_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    deactivate_date: Optional[datetime] = None


class ClientCreate(ClientBase):
    client_id: str


class ClientResponse(ClientCreate):
    pass


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    limits: Optional[QuotaDetail] = None
    consumed: Optional[QuotaDetail] = None
    status: Optional[ClientStatus] = None
    deactivate_date: Optional[datetime] = None
