import json
import asyncio
import base64
import time

import httpx
import pytest
import rsa
from jose import jwt
from fastapi import FastAPI

from common.security import engine


def test_policy_files_are_explicit_and_unique():
    for path in ("api/admin/s03-policy.json", "api/news-handler/s03-policy.json", "api/common/security/runtime-policy.json"):
        with open(path, encoding="utf-8") as handle:
            rows = json.load(handle)
        policies = [engine.Policy.parse(row) for row in rows]
        assert len({(policy.method, policy.path) for policy in policies}) == len(policies)
        assert all(policy.callers and policy.action for policy in policies)


def test_owner_scope_requires_human():
    with pytest.raises(ValueError, match="requires a user"):
        engine.Policy.parse({
            "method": "GET", "path": "/item/{id}", "action": "item:read",
            "callers": ["caller"], "user_required": False, "roles": [], "scope": "own",
        })


def test_internal_route_denies_untrusted_callers_and_wrong_user(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "jwt", object())
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/item/{item_id}")
    async def get_item(item_id: str):
        return {"item_id": item_id}

    path = tmp_path / "policy.json"
    path.write_text(json.dumps([{
        "method": "GET", "path": "/item/{item_id}", "action": "item:read",
        "callers": ["gateway"], "user_required": True, "roles": [], "scope": "own",
    }]), encoding="utf-8")

    async def fake_verify(self, token, *, audience, clients):
        if token == "service":
            if audience != "resource" or "gateway" not in clients:
                raise AssertionError("unexpected service policy")
            return {"azp": "gateway", "sub": "service-sub", "preferred_username": "service-account-gateway"}
        if token == "user":
            if "web" not in clients:
                raise AssertionError("unexpected user policy")
            return {"azp": "web", "sub": "user-sub", "iss": "https://issuer", "realm_access": {"roles": []}}
        if token == "wrong-service":
            return {"azp": "other", "sub": "service-sub", "preferred_username": "service-account-other"}
        raise AssertionError("unexpected token")

    monkeypatch.setattr(engine.KeycloakVerifier, "verify", fake_verify)

    async def owner_check(request, call):
        return request.path_params["item_id"] == "owned" and call.user_sub == "user-sub"

    guard = engine.InternalSecurity(app, audience="resource", issuer="https://issuer",
                                    jwks_url="https://issuer/certs", policy_file=str(path),
                                    user_clients=frozenset({"web"}), owner_check=owner_check)
    guard.install()
    async def requests():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/item/owned")).status_code == 401
            assert (await client.get("/item/owned", headers={"Authorization": "Bearer service"})).status_code == 401
            assert (await client.get("/item/owned", headers={"Authorization": "Bearer wrong-service", engine.USER_TOKEN_HEADER: "user"})).status_code == 401
            headers = {"Authorization": "Bearer service", engine.USER_TOKEN_HEADER: "user"}
            assert (await client.get("/item/other", headers=headers)).status_code == 403
            assert (await client.get("/item/owned", headers=headers)).status_code == 200

    asyncio.run(asyncio.wait_for(requests(), timeout=10))


def test_route_without_policy_cannot_start(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "jwt", object())
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/uncovered")
    async def uncovered():
        return {}

    path = tmp_path / "empty.json"
    path.write_text("[]", encoding="utf-8")
    guard = engine.InternalSecurity(app, audience="resource", issuer="https://issuer",
                                    jwks_url="https://issuer/certs", policy_file=str(path),
                                    user_clients=frozenset({"web"}))
    with pytest.raises(ValueError, match="Missing policy"):
        guard.install()


def test_real_signature_issuer_audience_and_client():
    public, private = rsa.newkeys(1024)
    def b64(value):
        return base64.urlsafe_b64encode(value.to_bytes((value.bit_length() + 7) // 8, "big")).decode().rstrip("=")

    key = {"kty": "RSA", "kid": "local", "use": "sig", "n": b64(public.n), "e": b64(public.e)}
    verifier = engine.KeycloakVerifier(issuer="https://issuer", jwks_url="https://issuer/certs")

    async def fake_key(kid):
        assert kid == "local"
        return key

    verifier._key = fake_key
    now = int(time.time())
    claims = {"sub": "user", "iss": "https://issuer", "aud": "resource", "azp": "web", "iat": now, "exp": now + 60}

    def signed(values):
        return jwt.encode(values, private.save_pkcs1().decode(), algorithm="RS256", headers={"kid": "local"})

    async def checks():
        assert (await verifier.verify(signed(claims), audience="resource", clients=frozenset({"web"})))["sub"] == "user"
        for changed in ({"iss": "https://wrong"}, {"aud": "wrong"}, {"azp": "wrong"}, {"exp": now - 1}):
            with pytest.raises(Exception) as exc:
                await verifier.verify(signed({**claims, **changed}), audience="resource", clients=frozenset({"web"}))
            assert exc.value.status_code == 401
        with pytest.raises(Exception) as exc:
            await verifier.verify(signed({**claims, "sub": ""}), audience="resource", clients=frozenset({"web"}))
        assert exc.value.status_code == 401

    asyncio.run(checks())
