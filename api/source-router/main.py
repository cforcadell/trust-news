import logging
import math
import os

from fastapi import FastAPI, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, ConfigDict, field_validator

from common.utils.logging_utils import configure_single_line_json_logging
from common.utils.llm_runtime import fetch_llm_runtime_override

from .app.config import get_settings
from .app.repository import SourceRouteRepository
from .app.routes.source_routes import router
from .app.service import SourceRouterService


configure_single_line_json_logging(logging.INFO)
settings = get_settings()
app = FastAPI(title="TrustNews Source Router", docs_url=None, redoc_url=None)
app.include_router(router)


class LLMRuntimeConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str | None = None
    model: str | None = None
    temperature: float | None = None
    config_version: int | None = None

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value):
        if value is None:
            return value
        value = value.strip().lower()
        if not value:
            raise ValueError("provider no puede estar vacío")
        return value

    @field_validator("model")
    @classmethod
    def validate_model(cls, value):
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("model no puede estar vacío")
        return value

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, value):
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ValueError("temperature debe ser un número finito mayor o igual que cero")
        return value


@app.on_event("startup")
async def startup() -> None:
    client = AsyncIOMotorClient(settings.mongo_uri, tz_aware=True)
    database = client[settings.mongo_dbname]
    repository = SourceRouteRepository(
        database[settings.collection],
        database[settings.profiles_collection],
    )
    await repository.ensure_indexes()
    app.state.mongo_client = client
    app.state.source_router_service = SourceRouterService(repository, settings)
    override = await fetch_llm_runtime_override(
        os.getenv("ADMIN_URL", "http://admin-service.apis.svc.cluster.local:8400"),
        "llm:source-router",
        logging.getLogger("source-router"),
    )
    if override:
        try:
            app.state.source_router_service.update_llm_runtime_config(**override)
            logging.getLogger("source-router").info("Applied persisted LLM runtime override for source-router")
        except Exception as exc:
            logging.getLogger("source-router").warning("Invalid persisted LLM override; using defaults: %s", exc.__class__.__name__)


@app.on_event("shutdown")
async def shutdown() -> None:
    client = getattr(app.state, "mongo_client", None)
    if client:
        client.close()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "source-router"}


@app.get("/ready")
async def ready():
    repository = app.state.source_router_service.repository
    await repository.collection.database.command("ping")
    return {"status": "ready", "service": "source-router"}


@app.get("/admin/config", tags=["Admin"])
async def get_admin_config():
    return app.state.source_router_service.llm_runtime_config()


@app.put("/admin/config", tags=["Admin"])
async def update_admin_config(config: LLMRuntimeConfigUpdate):
    try:
        return {
            "status": "ok",
            "config": app.state.source_router_service.update_llm_runtime_config(**config.model_dump(exclude_none=True)),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
