import os
from dataclasses import dataclass

from common.utils.mongo import build_mongo_uri_from_env


@dataclass(frozen=True)
class Settings:
    mongo_uri: str
    mongo_dbname: str
    collection: str
    search_provider: str
    discovery_max_results: int
    llm_provider: str
    llm_model: str
    llm_temperature: float
    refresh_seconds: int
    max_sources: int
    router_version: str


def get_settings() -> Settings:
    return Settings(
        mongo_uri=build_mongo_uri_from_env(),
        mongo_dbname=os.getenv("MONGO_DBNAME", "newsdb"),
        collection=os.getenv("SOURCE_ROUTES_COLLECTION", "source_routes"),
        search_provider=os.getenv("SEARCH_PROVIDER", "exa").lower(),
        discovery_max_results=int(os.getenv("SOURCE_ROUTER_DISCOVERY_MAX_RESULTS", "12")),
        llm_provider=os.getenv("LLM_PROVIDER", os.getenv("AI_PROVIDER", "openrouter")).lower(),
        llm_model=os.getenv("LLM_MODEL", os.getenv("MODEL", "google/gemini-2.5-flash-lite")),
        llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
        refresh_seconds=int(os.getenv("SOURCE_ROUTE_REFRESH_SECONDS", "2592000")),
        max_sources=int(os.getenv("SOURCE_ROUTER_MAX_SOURCES", "8")),
        router_version=os.getenv("SOURCE_ROUTER_VERSION", "source-router-hybrid-v1"),
    )
