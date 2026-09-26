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


def test_deployed_llm_recommendation_compares_role_specific_token_cost():
    admin = importlib.import_module("admin.main")
    catalog = {
        "google/gemini-2.5-flash-lite": {
            "id": "google/gemini-2.5-flash-lite",
            "name": "Gemini 2.5 Flash Lite",
            "pricing": {"prompt": "0.0000001", "completion": "0.0000004"},
        },
        "google/gemini-3.8-flash": {
            "id": "google/gemini-3.8-flash",
            "name": "Gemini 3.8 Flash",
            "pricing": {"prompt": "0.00000075", "completion": "0.00000375"},
        },
        "openai/gpt-5-nano": {
            "id": "openai/gpt-5-nano",
            "name": "GPT-5 Nano",
            "pricing": {"prompt": "0.00000005", "completion": "0.0000004"},
        },
        "qwen/qwen3.7-flash": {
            "id": "qwen/qwen3.7-flash",
            "name": "Qwen3.7 Flash",
            "pricing": {"prompt": "0.00000003", "completion": "0.00000013"},
        },
    }

    recommendation = admin.build_deployed_recommendation(
        target_id="generate-asertions",
        target_kind="component",
        current={"provider": "openrouter", "model": "google/gemini-2.5-flash-lite"},
        catalog=catalog,
        profile=admin.recommendation_profile("generate-asertions"),
    )

    assert [option.tier for option in recommendation.options] == ["premium", "similar", "budget"]
    assert recommendation.options[0].model == "google/gemini-3.8-flash"
    assert recommendation.options[1].model == "openai/gpt-5-nano"
    assert recommendation.options[2].model == "qwen/qwen3.7-flash"
    assert recommendation.workload_key == "generateAssertions"
    assert recommendation.reason_key == "generateAssertions"
    assert recommendation.input_tokens == 3000
    assert recommendation.output_tokens == 1200
    assert recommendation.estimated_current_cost_usd == pytest.approx(0.00078)
    assert recommendation.options[0].estimated_cost_usd == pytest.approx(0.00675)
    assert recommendation.options[0].estimated_cost_delta_usd == pytest.approx(0.00597)
    assert recommendation.options[0].estimated_cost_delta_percent == pytest.approx(765.38)
    assert recommendation.options[2].estimated_cost_usd < recommendation.estimated_current_cost_usd


def test_deployed_llm_recommendation_does_not_invent_non_openrouter_current_price():
    admin = importlib.import_module("admin.main")
    catalog = {
        "mistralai/mistral-small-2603": {
            "id": "mistralai/mistral-small-2603",
            "name": "Mistral Small 4",
            "pricing": {"prompt": "0.00000015", "completion": "0.0000006"},
        },
    }

    recommendation = admin.build_deployed_recommendation(
        target_id="validator-a",
        target_kind="validator",
        current={"provider": "gemini", "model": "gemini-direct"},
        catalog=catalog,
        profile=admin.recommendation_profile(
            "validator", {"name": "LLM_MEMORY_VALIDATION"}, None,
        ),
    )

    assert recommendation.current_price is None
    assert recommendation.estimated_current_cost_usd is None
    assert all(option.estimated_cost_delta_usd is None for option in recommendation.options)
    assert all(option.estimated_cost_delta_percent is None for option in recommendation.options)


def test_deployed_llm_recommendation_keeps_current_cost_without_alternatives():
    admin = importlib.import_module("admin.main")
    current_model = "custom/current-model"
    catalog = {
        current_model: {
            "id": current_model,
            "name": "Current",
            "pricing": {"prompt": "0.000001", "completion": "0.000002"},
        },
    }

    recommendation = admin.build_deployed_recommendation(
        target_id="generate-asertions",
        target_kind="component",
        current={"provider": "openrouter", "model": current_model},
        catalog=catalog,
        profile=admin.recommendation_profile("generate-asertions"),
    )

    assert recommendation is not None
    assert recommendation.options == []
    assert recommendation.estimated_current_cost_usd == pytest.approx(0.0054)


def test_similar_recommendation_accepts_a_wider_cost_range():
    admin = importlib.import_module("admin.main")
    catalog = {
        "current": {
            "id": "current", "name": "Current",
            "pricing": {"prompt": "0.000001", "completion": "0"},
        },
        "four-times": {
            "id": "four-times", "name": "Four times",
            "pricing": {"prompt": "0.000004", "completion": "0"},
        },
    }
    profile = {
        "workload": "test", "reason": "test", "input_tokens": 1000, "output_tokens": 0,
        "tiers": {"premium": [], "similar": ["four-times"], "budget": []},
    }

    recommendation = admin.build_deployed_recommendation(
        target_id="validator", target_kind="validator",
        current={"provider": "openrouter", "model": "current"},
        catalog=catalog, profile=profile,
    )

    similar = next(option for option in recommendation.options if option.tier == "similar")
    assert similar.model == "four-times"


def test_similar_recommendation_falls_back_to_a_curated_cheaper_model():
    admin = importlib.import_module("admin.main")
    catalog = {
        "current": {
            "id": "current", "name": "Current",
            "pricing": {"prompt": "0.000001", "completion": "0"},
        },
        "too-expensive": {
            "id": "too-expensive", "name": "Too expensive",
            "pricing": {"prompt": "0.000010", "completion": "0"},
        },
        "cheaper": {
            "id": "cheaper", "name": "Cheaper",
            "pricing": {"prompt": "0.0000005", "completion": "0"},
        },
    }
    profile = {
        "workload": "test", "reason": "test", "input_tokens": 1000, "output_tokens": 0,
        "tiers": {
            "premium": ["too-expensive"], "similar": ["too-expensive"],
            "budget": ["cheaper"],
        },
    }

    recommendation = admin.build_deployed_recommendation(
        target_id="validator", target_kind="validator",
        current={"provider": "openrouter", "model": "current"},
        catalog=catalog, profile=profile,
    )

    similar = next(option for option in recommendation.options if option.tier == "similar")
    assert similar.model == "cheaper"


def test_similar_recommendation_falls_back_to_the_priced_catalog():
    admin = importlib.import_module("admin.main")
    catalog = {
        "current": {
            "id": "current", "name": "Current",
            "pricing": {"prompt": "0.000001", "completion": "0"},
        },
        "catalog-alternative": {
            "id": "catalog-alternative", "name": "Catalog alternative",
            "pricing": {"prompt": "0.0000008", "completion": "0"},
        },
    }
    profile = {
        "workload": "test", "reason": "test", "input_tokens": 1000,
        "output_tokens": 0, "tiers": {"premium": [], "similar": [], "budget": []},
    }

    recommendation = admin.build_deployed_recommendation(
        target_id="validator", target_kind="validator",
        current={"provider": "openrouter", "model": "current"},
        catalog=catalog, profile=profile,
    )

    similar = next(option for option in recommendation.options if option.tier == "similar")
    assert similar.model == "catalog-alternative"


def test_global_news_cost_limit_constrains_every_recommendation_tier():
    admin = importlib.import_module("admin.main")
    price = admin.OpenRouterPrice(
        prompt_per_token_usd="0", completion_per_token_usd="0",
        prompt_per_million_usd=0, completion_per_million_usd=0,
    )

    def deployed(target_id, target_kind, workload_key, current_cost, premium_cost):
        return admin.DeployedLLMRecommendation(
            target_id=target_id, target_kind=target_kind, workload=workload_key,
            workload_key=workload_key, current_provider="openrouter", current_model="current",
            input_tokens=1, output_tokens=1, estimated_current_cost_usd=current_cost,
            options=[admin.OpenRouterRecommendationOption(
                tier="premium", model="premium", name="Premium", price=price,
                estimated_cost_usd=premium_cost,
            )],
            reason="test",
        )

    recommendations = [
        deployed("generate-asertions", "component", "generateAssertions", 0.10, 0.20),
        deployed("source-router", "component", "sourceRouter", 0.01, 0.02),
        deployed("local-validator", "validator", "ragLocal", 0.05, 0.15),
    ]

    totals = admin.constrain_recommendations_by_news_cost(recommendations, 0.60)

    assert totals["current"] == pytest.approx(0.40)
    assert totals["premium"] == pytest.approx(0.55)
    assert totals["premium"] <= 0.60
    assert any(option.tier == "premium" for option in recommendations[0].options)
    assert not any(option.tier == "premium" for option in recommendations[2].options)

    impossible = copy.deepcopy(recommendations)
    for recommendation in impossible:
        recommendation.options = [admin.OpenRouterRecommendationOption(
            tier="premium", model="premium", name="Premium", price=price,
            estimated_cost_usd=recommendation.estimated_current_cost_usd,
        )]
    impossible_totals = admin.constrain_recommendations_by_news_cost(impossible, 0.20)

    assert impossible_totals["premium"] is None
    assert all(not any(option.tier == "premium" for option in item.options) for item in impossible)


def test_global_limit_replaces_an_expensive_similar_option_with_savings():
    admin = importlib.import_module("admin.main")
    price = admin.OpenRouterPrice(
        prompt_per_token_usd="0", completion_per_token_usd="0",
        prompt_per_million_usd=0, completion_per_million_usd=0,
    )
    recommendation = admin.DeployedLLMRecommendation(
        target_id="generate-asertions", target_kind="component", workload="test",
        current_provider="openrouter", current_model="current",
        input_tokens=1, output_tokens=1, estimated_current_cost_usd=0.10,
        options=[
            admin.OpenRouterRecommendationOption(
                tier="similar", model="expensive", name="Expensive", price=price,
                estimated_cost_usd=0.30,
            ),
            admin.OpenRouterRecommendationOption(
                tier="budget", model="cheaper", name="Cheaper", price=price,
                estimated_cost_usd=0.05,
            ),
        ],
        reason="test",
    )

    totals = admin.constrain_recommendations_by_news_cost([recommendation], 0.15)

    similar = next(option for option in recommendation.options if option.tier == "similar")
    assert similar.model == "cheaper"
    assert totals["similar"] == pytest.approx(0.05)
    assert totals["similar"] <= 0.15


def test_global_limit_degrades_premium_before_hiding_the_alternative():
    admin = importlib.import_module("admin.main")
    price = admin.OpenRouterPrice(
        prompt_per_token_usd="0", completion_per_token_usd="0",
        prompt_per_million_usd=0, completion_per_million_usd=0,
    )
    recommendation = admin.DeployedLLMRecommendation(
        target_id="generate-asertions", target_kind="component", workload="test",
        current_provider="openrouter", current_model="current",
        input_tokens=1, output_tokens=1, estimated_current_cost_usd=0.10,
        options=[
            admin.OpenRouterRecommendationOption(
                tier="premium", model="expensive", name="Expensive", price=price,
                estimated_cost_usd=0.30,
            ),
            admin.OpenRouterRecommendationOption(
                tier="similar", model="compatible", name="Compatible", price=price,
                estimated_cost_usd=0.12,
            ),
            admin.OpenRouterRecommendationOption(
                tier="budget", model="cheaper", name="Cheaper", price=price,
                estimated_cost_usd=0.05,
            ),
        ],
        reason="test",
    )

    totals = admin.constrain_recommendations_by_news_cost([recommendation], 0.15)

    premium = next(option for option in recommendation.options if option.tier == "premium")
    assert premium.model == "compatible"
    assert totals["premium"] == pytest.approx(0.12)
    assert totals["premium"] <= 0.15


@pytest.mark.asyncio
async def test_deployed_recommendations_cover_components_and_each_llm_validator(monkeypatch):
    admin = importlib.import_module("admin.main")
    current_model = "google/gemini-2.5-flash-lite"

    async def component(component):
        return {"actual": {"provider": "openrouter", "model": current_model}}

    async def validators():
        return [
            {"validator_id": "0xofficial", "provider": "openrouter", "model": current_model,
             "validator_type": {"name": "RAG_EVIDENCE_VALIDATION"}, "evidence_search_strategy": "EXT_ONLY_OFFICIAL"},
            {"validator_id": "0xlocal", "provider": "openrouter", "model": current_model,
             "validator_type": {"name": "RAG_EVIDENCE_VALIDATION"}, "evidence_search_strategy": "LOCAL"},
            {"validator_id": "0xdeterministic", "provider": "none", "model": "",
             "validator_type": {"name": "DETERMINISTIC_VALIDATION"}, "evidence_search_strategy": None},
        ]

    def model(model_id, prompt="0.000001", completion="0.000002"):
        return {"id": model_id, "name": model_id, "pricing": {"prompt": prompt, "completion": completion}}

    catalog = {
        model_id: model(model_id) for model_id in (
            current_model,
            "google/gemini-3.8-flash",
            "google/gemini-3.5-flash-lite",
            "openai/gpt-5.6-sol",
            "mistralai/mistral-medium-3-5",
        )
    }
    monkeypatch.setattr(admin, "get_llm_component", component)
    monkeypatch.setattr(admin, "discover_validators", validators)

    recommendations = await admin.deployed_llm_recommendations(catalog)

    assert [item.target_id for item in recommendations] == [
        "generate-asertions", "source-router", "0xofficial", "0xlocal",
    ]
    assert [item.options[0].model for item in recommendations] == [
        "google/gemini-3.8-flash", "google/gemini-3.8-flash",
        "openai/gpt-5.6-sol", "mistralai/mistral-medium-3-5",
    ]


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
                "/admin/llm/models/openrouter?limit=12&max_news_cost_usd=0.25",
                headers={"x-test-auth": "admin"},
            )
            assert recommended.status_code == 200
            assert recommended.json()["target"].endswith(
                "/ai/openrouter/recommendations?limit=12&max_news_cost_usd=0.25"
            )
    finally:
        gateway.app.dependency_overrides.pop(gateway.get_current_user, None)
