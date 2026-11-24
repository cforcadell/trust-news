import json
import logging

import pytest
from fastapi import HTTPException, Request

from gateway.security import RequestSecurityMiddleware
from gateway import main as gateway


def http_scope(*, method="POST", path="/orders/publishNew", headers=None):
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers or [],
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
    }


async def run_asgi(app, scope, incoming):
    messages = iter(incoming)
    sent = []

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    return sent


def response_status(messages):
    return next(message["status"] for message in messages if message["type"] == "http.response.start")


@pytest.mark.asyncio
async def test_rejects_declared_oversized_body_without_calling_app(caplog):
    called = False

    async def downstream(scope, receive, send):
        nonlocal called
        called = True

    middleware = RequestSecurityMiddleware(
        downstream, max_request_body_bytes=8, logger=logging.getLogger("gateway-security-test")
    )
    scope = http_scope(headers=[(b"content-length", b"9")])

    with caplog.at_level(logging.WARNING, logger="gateway-security-test"):
        sent = await run_asgi(middleware, scope, [])

    assert response_status(sent) == 413
    assert called is False
    event = json.loads(caplog.records[-1].message)
    assert event["status"] == 413
    assert event["path"] == "/orders/publishNew"


@pytest.mark.asyncio
async def test_rejects_chunked_body_when_accumulated_size_exceeds_limit():
    called = False

    async def downstream(scope, receive, send):
        nonlocal called
        called = True

    middleware = RequestSecurityMiddleware(
        downstream, max_request_body_bytes=8, logger=logging.getLogger("gateway-security-test")
    )
    incoming = [
        {"type": "http.request", "body": b"12345", "more_body": True},
        {"type": "http.request", "body": b"6789", "more_body": False},
    ]

    sent = await run_asgi(middleware, http_scope(), incoming)

    assert response_status(sent) == 413
    assert called is False


@pytest.mark.asyncio
async def test_replays_allowed_body_and_adds_request_id():
    received_body = b""

    async def downstream(scope, receive, send):
        nonlocal received_body
        while True:
            message = await receive()
            received_body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 202, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = RequestSecurityMiddleware(
        downstream, max_request_body_bytes=8, logger=logging.getLogger("gateway-security-test")
    )
    incoming = [{"type": "http.request", "body": b"12345678", "more_body": False}]

    sent = await run_asgi(middleware, http_scope(), incoming)

    assert response_status(sent) == 202
    assert received_body == b"12345678"
    response_start = next(message for message in sent if message["type"] == "http.response.start")
    assert any(name == b"x-request-id" for name, _ in response_start["headers"])


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403, 405, 429, 500])
async def test_logs_security_relevant_statuses(status_code, caplog):
    async def downstream(scope, receive, send):
        await receive()
        await send({"type": "http.response.start", "status": status_code, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    logger_name = f"gateway-security-status-{status_code}"
    middleware = RequestSecurityMiddleware(
        downstream, max_request_body_bytes=8, logger=logging.getLogger(logger_name)
    )
    incoming = [{"type": "http.request", "body": b"", "more_body": False}]

    with caplog.at_level(logging.INFO, logger=logger_name):
        await run_asgi(middleware, http_scope(method="GET"), incoming)

    event = json.loads(caplog.records[-1].message)
    assert event["status"] == status_code


@pytest.mark.asyncio
async def test_global_order_list_requires_explicit_read_all_role(monkeypatch):
    monkeypatch.setenv("S03_ENABLED", "true")
    request = Request(http_scope(method="GET", path="/orders/list"))
    trust_admin_only = {"sub": "admin", "realm_access": {"roles": ["trust-admin"]}}

    with pytest.raises(HTTPException) as denied:
        await gateway.proxy_get_news(request, view_all=True, auth_payload=trust_admin_only)
    assert denied.value.status_code == 403

    integration = {
        "sub": "integration-sub", "_s03_actor_type": "integration",
        "_s03_integration": {"quota_id": "integration-one"},
        "realm_access": {"roles": ["trust-read-all"]},
    }
    with pytest.raises(HTTPException) as integration_denied:
        await gateway.proxy_get_news(request, view_all=True, auth_payload=integration)
    assert integration_denied.value.status_code == 403


@pytest.mark.asyncio
async def test_read_all_role_controls_gateway_list_forwarding(monkeypatch):
    monkeypatch.setenv("S03_ENABLED", "true")
    forwarded = []

    async def fake_proxy(request, target_url):
        forwarded.append(target_url)
        return {"forwarded": target_url}

    monkeypatch.setattr(gateway, "proxy_request", fake_proxy)
    request = Request(http_scope(method="GET", path="/orders/list"))
    user = {"sub": "reader", "realm_access": {"roles": ["trust-read-all"]}}

    response = await gateway.proxy_get_news(request, view_all=True, auth_payload=user)
    assert "admin=true" in response["forwarded"]
    response = await gateway.proxy_get_news(request, view_all=False, auth_payload=user)
    assert "admin=false" in response["forwarded"]
