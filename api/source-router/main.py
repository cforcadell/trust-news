import logging

from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient

from common.utils.logging_utils import configure_single_line_json_logging

from .app.config import get_settings
from .app.repository import SourceRouteRepository
from .app.routes.source_routes import router
from .app.service import SourceRouterService


configure_single_line_json_logging(logging.INFO)
settings = get_settings()
app = FastAPI(title="TrustNews Source Router", docs_url=None, redoc_url=None)
app.include_router(router)


@app.on_event("startup")
async def startup() -> None:
    client = AsyncIOMotorClient(settings.mongo_uri, tz_aware=True)
    repository = SourceRouteRepository(client[settings.mongo_dbname][settings.collection])
    await repository.ensure_indexes()
    app.state.mongo_client = client
    app.state.source_router_service = SourceRouterService(repository, settings)


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
