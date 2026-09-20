"""Regression tests for the non-secret, centrally orchestrated LLM runtime API."""

import copy
import importlib
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from gateway import main as gateway


ROOT = Path(__file__).resolve().parents[2]


def load_generate():
    path = ROOT / "api/generate-asertions/main.py"
    spec = importlib.util.spec_from_file_location("llm_runtime_generate", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_validator():
    os.environ.update({
        "ACCOUNT_ADDRESS": "0x0000000000000000000000000000000000000001",
        "CONTRACT_ADDRESS": "0x0000000000000000000000000000000000000002",
        "CONTRACT_ABI_PATH": str(ROOT / "smart-contracts/artifacts/contracts/TrustNews.sol/TrustNews.json"),
        "RPC_URL": "http://127.0.0.1:1",
        "PRIVATE_KEY": "0x" + "1" * 64,
        "VALIDATOR_TYPE": "4",
        "AI_PROVIDER": "none",
    })
    path = ROOT / "api/validate-asertions/main.py"
    spec = importlib.util.spec_from_file_location("llm_runtime_validator", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_runtime_schemas_reject_secret_fields_and_do_not_serialize_them():
    generate = load_generate()
    validator = load_validator()
    source_router = importlib.import_module("source-router.main")

    for schema in (generate.AdminConfigUpdate, validator.AdminConfigUpdate, source_router.LLMRuntimeConfigUpdate):
        for field in ("api_key", "private_key", "password", "access_token", "client_secret"):
            with pytest.raises(ValidationError):
                schema.model_validate({"provider": "openrouter", "model": "safe-model", field: "not-allowed"})

    generate_response = generate.normalize_admin_config_response().model_dump()
    validator_response = validator.normalize_admin_config_response().model_dump()
    for response in (generate_response, validator_response):
        assert not {"api_key", "private_key", "password", "token", "secret"}.intersection(response)


@pytest.mark.asyncio
async def test_runtime_http_endpoints_return_4xx_for_secret_input():
    generate = load_generate()
    validator = load_validator()
    source_router = importlib.import_module("source-router.main")

    for app in (generate.app, validator.app, source_router.app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal") as client:
            response = await client.put("/admin/config", json={
                "provider": "openrouter", "model": "safe-model", "api_key": "must-be-rejected",
            })
        assert response.status_code == 422


def test_source_router_hot_update_changes_effective_classifier_settings():
    service_module = importlib.import_module("source-router.app.service")
    config_module = importlib.import_module("source-router.app.config")
    settings = config_module.Settings(
        mongo_uri="mongodb://unused", mongo_dbname="unused", collection="routes", profiles_collection="profiles",
        search_provider="exa", discovery_max_results=3, llm_provider="openrouter", llm_model="model-a",
        llm_temperature=0.0, refresh_seconds=60, max_sources=3, router_version="test",
    )
    service = service_module.SourceRouterService(repository=SimpleNamespace(), settings=settings)

    effective = service.update_llm_runtime_config(provider="gemini", model="model-b", temperature=0.2, config_version=4)

    assert effective["provider"] == "gemini"
    assert effective["model"] == "model-b"
    assert effective["config_version"] == 4
    assert service.classifier_settings().llm_model == "model-b"


class MemoryConfigCollection:
    def __init__(self):
        self.documents = {}

    async def find_one(self, query):
        document = self.documents.get(query["_id"])
        return copy.deepcopy(document) if document else None

    async def update_one(self, query, update, upsert=False):
        key = query["_id"]
        document = self.documents.get(key)
        if document is None:
            assert upsert
            document = {"_id": key, **copy.deepcopy(update.get("$setOnInsert", {}))}
            self.documents[key] = document
        document.update(copy.deepcopy(update.get("$set", {})))


@pytest.mark.asyncio
async def test_dynamic_validator_discovery_filters_and_updates_only_selected_validator(monkeypatch):
    admin = importlib.import_module("admin.main")
    registry = [
        {"validator_id": "0xaaa", "service_url": "http://validator-a", "validator_type": {"id": 3, "name": "RAG_EVIDENCE_VALIDATION"},
         "evidence_search_strategy": "LOCAL", "categories": [1], "status": "ACTIVE"},
        {"validator_id": "0xbbb", "service_url": "http://validator-b", "validator_type": {"id": 3, "name": "RAG_EVIDENCE_VALIDATION"},
         "evidence_search_strategy": "EXT_ONLY_OFFICIAL", "categories": [2], "status": "ACTIVE"},
        {"validator_id": "0xccc", "service_url": "http://validator-c", "validator_type": {"id": 1, "name": "LLM_MEMORY_VALIDATION"},
         "evidence_search_strategy": None, "categories": [3], "status": "ACTIVE"},
    ]
    effective = {
        "http://validator-a": {"provider": "openrouter", "model": "model-a", "temperature": 0.1, "config_version": 0},
        "http://validator-b": {"provider": "openrouter", "model": "model-b", "temperature": 0.1, "config_version": 0},
        "http://validator-c": {"provider": "gemini", "model": "model-c", "temperature": 0.1, "config_version": 0},
    }

    async def discover():
        return copy.deepcopy(registry)

    async def read(url):
        return copy.deepcopy(effective[url])

    async def apply(url, desired):
        effective[url] = {key: desired[key] for key in ("provider", "model", "temperature", "config_version")}
        return copy.deepcopy(effective[url])

    monkeypatch.setattr(admin, "discover_validators", discover)
    monkeypatch.setattr(admin, "service_config", read)
    monkeypatch.setattr(admin, "apply_service_config", apply)
    monkeypatch.setattr(admin, "config_collection", MemoryConfigCollection())

    listed = await admin.list_llm_validators(type=None, strategy=None)
    assert [item["validator_id"] for item in listed["validators"]] == ["0xaaa", "0xbbb", "0xccc"]
    rag = await admin.list_llm_validators(type="RAG_EVIDENCE_VALIDATION", strategy="LOCAL")
    assert [item["validator_id"] for item in rag["validators"]] == ["0xaaa"]

    await admin.update_llm_validator(
        "0xaaa", admin.LLMRuntimeUpdate(provider="openrouter", model="model-a-new", temperature=0.2),
        SimpleNamespace(headers={"x-assermetry-admin-user": "alice"}),
    )
    assert effective["http://validator-a"]["model"] == "model-a-new"
    assert effective["http://validator-b"]["model"] == "model-b"
    detail_b = await admin.get_llm_validator("0xbbb")
    assert detail_b["actual"]["model"] == "model-b"


@pytest.mark.asyncio
async def test_gateway_llm_admin_requires_verified_admin_role(monkeypatch):
    async def claims(request: Request):
        state = request.headers.get("x-test-auth")
        if state == "invalid":
            raise HTTPException(status_code=401, detail="invalid jwt")
        return {"sub": "alice", "realm_access": {"roles": ["trust-admin"] if state == "admin" else []}}

    async def proxy(request, target_url, auth_payload):
        return JSONResponse({"target": target_url, "updated_by": auth_payload["sub"]})

    monkeypatch.setitem(gateway.app.dependency_overrides, gateway.get_current_user, claims)
    monkeypatch.setattr(gateway, "proxy_admin_request", proxy)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url="http://gateway") as client:
            assert (await client.get("/admin/llm/components", headers={"x-test-auth": "invalid"})).status_code == 401
            assert (await client.get("/admin/llm/components", headers={"x-test-auth": "user"})).status_code == 403
            allowed = await client.get("/admin/llm/components", headers={"x-test-auth": "admin"})
            assert allowed.status_code == 200
            assert allowed.json()["updated_by"] == "alice"
            assert (await client.get("/admin/llm/models/openrouter", headers={"x-test-auth": "invalid"})).status_code == 401
            assert (await client.get("/admin/llm/models/openrouter", headers={"x-test-auth": "user"})).status_code == 403
            recommended = await client.get(
                "/admin/llm/models/openrouter?limit=12", headers={"x-test-auth": "admin"},
            )
            assert recommended.status_code == 200
            assert recommended.json()["target"].endswith("/ai/openrouter/recommendations?limit=12")
    finally:
        gateway.app.dependency_overrides.pop(gateway.get_current_user, None)
