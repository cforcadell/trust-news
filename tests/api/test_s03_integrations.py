import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials

from common.security import engine
from common.utils.quotas_client import integration_quota_payload
from gateway import main as gateway
from admin import main as admin


def test_integration_policy_rejects_human_roles():
    row = {"method": "GET", "path": "/item/{item_id}", "action": "orders:read",
           "callers": ["gateway"], "user_required": True, "roles": [],
           "scope": "own", "actors": ["human", "integration"]}
    assert engine.Policy.parse(row).actors == frozenset({"human", "integration"})
    with pytest.raises(ValueError, match="Human roles"):
        engine.Policy.parse({**row, "roles": ["trust-admin"]})


def test_idempotency_key_is_bound_to_operation_type():
    first = integration_quota_payload("operation_123456", "news_generation", {"text": "example"},
                                      "integration_one", "/publishNew")
    second = integration_quota_payload("operation_123456", "news_generation", {"text": "example"},
                                       "integration_one", "/publishWithAssertions")
    assert first["request_hash"] != second["request_hash"]


def test_integration_actor_requires_binding_action_owner_and_gate(monkeypatch, tmp_path):
    monkeypatch.setenv("S03_INTEGRATIONS_ENABLED", "true")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/item/{item_id}")
    async def item(item_id: str, request: Request):
        return {"actor": request.state.s03_call.actor_type,
                "integration_id": request.state.s03_call.integration_id}

    policy_file = tmp_path / "policy.json"
    policy_file.write_text(json.dumps([{
        "method": "GET", "path": "/item/{item_id}", "action": "orders:read",
        "callers": ["gateway"], "user_required": True, "roles": [],
        "scope": "own", "actors": ["human", "integration"],
    }]))

    async def verify(self, token, *, audience, clients):
        assert audience == "resource"
        if token == "gateway":
            return {"azp": "gateway", "preferred_username": "service-account-gateway", "sub": "service"}
        if token == "integration":
            assert clients is None
            return {"azp": "tnapi-one", "preferred_username": "service-account-tnapi-one",
                    "sub": "subject", "iss": "https://issuer"}
        if token == "shared":
            return {"azp": "TrustNewsApi", "preferred_username": "service-account-TrustNewsApi",
                    "sub": "subject", "iss": "https://issuer"}
        raise HTTPException(status_code=401, detail="Invalid token")

    async def resolve(claims, token, action):
        assert (claims["azp"], token, action) == ("tnapi-one", "integration", "orders:read")
        return {"integration_id": "one", "org_id": "org-one", "quota_id": "integration_one"}

    async def owner(request, call):
        return call.integration_id == "one" and request.path_params["item_id"] == "own"

    monkeypatch.setattr(engine.KeycloakVerifier, "verify", verify)
    engine.InternalSecurity(app, audience="resource", issuer="https://issuer",
                            jwks_url="https://issuer/certs", policy_file=str(policy_file),
                            user_clients=frozenset({"TrustNewsWeb"}), owner_check=owner,
                            integration_resolver=resolve).install()

    async def requests():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            headers = {"Authorization": "Bearer gateway", engine.USER_TOKEN_HEADER: "integration"}
            response = await client.get("/item/own", headers=headers)
            assert response.status_code == 200
            assert response.json() == {"actor": "integration", "integration_id": "one"}
            assert (await client.get("/item/other", headers=headers)).status_code == 403
            assert (await client.get("/item/own", headers={**headers, engine.USER_TOKEN_HEADER: "shared"})).status_code == 401
            monkeypatch.setenv("S03_INTEGRATIONS_ENABLED", "false")
            assert (await client.get("/item/own", headers=headers)).status_code == 403

    asyncio.run(requests())


def test_gateway_keeps_web_and_rejects_shared_client(monkeypatch):
    class Verifier:
        async def verify(self, token, *, audience, clients):
            assert audience == gateway.KEYCLOAK_EXPECTED_AUDIENCE and clients is None
            return {
                "web": {"azp": "TrustNewsWeb", "sub": "human"},
                "shared": {"azp": "TrustNewsApi", "sub": "old",
                           "preferred_username": "service-account-TrustNewsApi"},
                "new": {"azp": "tnapi-one", "sub": "service",
                        "preferred_username": "service-account-tnapi-one"},
            }[token]

    monkeypatch.setattr(gateway, "_s03_user_verifier", Verifier())
    monkeypatch.setattr(gateway, "KEYCLOAK_ALLOWED_CLIENT_IDS", {"TrustNewsWeb", "TrustNewsApi"})
    monkeypatch.setenv("S03_INTEGRATIONS_ENABLED", "true")

    async def resolve(claims, token, action):
        assert action == "orders:create"
        return {"integration_id": "one", "org_id": "org-one", "quota_id": "integration_one"}

    monkeypatch.setattr(gateway, "resolve_integration_remote", resolve)
    scope = {"type": "http", "method": "POST", "path": "/orders/publishNew",
             "headers": [], "route": type("Route", (), {"path": "/orders/publishNew"})()}
    request = Request(scope)

    async def checks():
        web = await gateway.get_current_user(request, HTTPAuthorizationCredentials(scheme="Bearer", credentials="web"))
        assert gateway.get_computed_client_id(web) == "user_human"
        with pytest.raises(HTTPException) as denied:
            await gateway.get_current_user(request, HTTPAuthorizationCredentials(scheme="Bearer", credentials="shared"))
        assert denied.value.status_code == 401
        integration = await gateway.get_current_user(request, HTTPAuthorizationCredentials(scheme="Bearer", credentials="new"))
        assert gateway.get_computed_client_id(integration) == "integration_one"
        assert gateway.is_admin_user(integration) is False

    asyncio.run(checks())


def test_admin_resolves_only_active_matching_binding(monkeypatch):
    from datetime import datetime, timedelta, timezone

    binding = {"integration_id": "one", "org_id": "org-one", "quota_id": "integration_one",
               "status": "active", "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
               "actions": ["orders:create"]}

    class Cursor:
        async def to_list(self, length):
            return [binding] if length == 2 else []

    class Bindings:
        def find(self, query, projection):
            assert query == {"issuer": "https://issuer", "azp": "tnapi-one", "sub": "subject"}
            return Cursor()

    class Organizations:
        async def find_one(self, query, projection):
            return {"_id": 1} if query == {
                "org_id": "org-one", "status": "active",
                "integrations.one.quota_id": "integration_one",
                "integrations.one.status": "Active",
            } else None

    monkeypatch.setattr(admin, "db", {"s03_integrations": Bindings(), "s03_organizations": Organizations()})
    claims = {"iss": "https://issuer", "azp": "tnapi-one", "sub": "subject"}

    async def checks():
        assert (await admin.resolve_integration_local(claims, "", "orders:create"))["quota_id"] == "integration_one"
        with pytest.raises(HTTPException) as denied:
            await admin.resolve_integration_local(claims, "", "orders:read")
        assert denied.value.status_code == 403
        binding["status"] = "suspended"
        with pytest.raises(HTTPException) as suspended:
            await admin.resolve_integration_local(claims, "", "orders:create")
        assert suspended.value.status_code == 403
        with pytest.raises(HTTPException) as shared:
            await admin.resolve_integration_local({**claims, "azp": "TrustNewsApi"}, "", "orders:create")
        assert shared.value.status_code == 401

    asyncio.run(checks())


def test_integration_quota_reserves_org_and_client_in_one_update(monkeypatch):
    from types import SimpleNamespace

    class OrganizationCollection:
        def __init__(self):
            self.calls = []

        async def find_one_and_update(self, query, update, **kwargs):
            self.calls.append((query, update))
            return {"org_id": "org-one"}

    organization = OrganizationCollection()
    monkeypatch.setattr(admin, "db", {"s03_organizations": organization})
    request = SimpleNamespace(state=SimpleNamespace(s03_call=SimpleNamespace(
        actor_type="integration", integration_id="one", org_id="org-one",
        quota_id="integration_one")))
    payload = admin.IntegrationQuotaOperation(
        field="news_generation", operation_id="request_12345678", request_hash="a" * 64)

    async def checks():
        assert (await admin.reserve_integration_quota("integration_one", payload, request))["created"] is True
        assert (await admin.consume_integration_quota("integration_one", payload, request))["state"] == "consumed"

    asyncio.run(checks())
    reserve_query, reserve_update = organization.calls[0]
    consume_query, consume_update = organization.calls[1]
    assert reserve_query["org_id"] == "org-one"
    assert len(reserve_query["$expr"]["$and"]) == 3  # capacity, organization and integration limits
    assert reserve_update["$inc"] == {
        "reserved.news_generation": 1,
        "integrations.one.reserved.news_generation": 1,
    }
    assert consume_query["org_id"] == "org-one"
    assert consume_update["$inc"] == {
        "reserved.news_generation": -1,
        "integrations.one.reserved.news_generation": -1,
        "consumed.news_generation": 1,
        "integrations.one.consumed.news_generation": 1,
    }
