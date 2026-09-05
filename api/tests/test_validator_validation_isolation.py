"""HTTP regression of Gateway -> News Handler with two synthetic owners.

Authentication is overridden with verified-claim fixtures; JWT validation and
real MongoDB/deployment isolation require their own integration checks.
"""
import copy
import importlib.util
import re
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException, Request

from gateway import main as gateway


def matches(document, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(matches(document, option) for option in expected):
                return False
            continue
        value = document
        for part in key.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if isinstance(expected, dict):
            for operator, operand in expected.items():
                if operator == "$in" and value not in operand:
                    return False
                if operator == "$regex" and not re.search(operand, str(value or ""), re.I):
                    return False
                if operator == "$type" and not isinstance(value, (int, float)):
                    return False
                if operator == "$gte" and (value is None or value < operand):
                    return False
                if operator not in {"$in", "$regex", "$options", "$type", "$gte"}:
                    raise AssertionError(f"Unsupported test query: {operator}")
        elif value != expected:
            return False
    return True


class Cursor:
    def __init__(self, documents):
        self.documents = copy.deepcopy(documents)

    def sort(self, *args):
        return self

    async def to_list(self, length):
        return self.documents[:length]

    def __aiter__(self):
        async def rows():
            for document in self.documents:
                yield document
        return rows()


class Collection:
    def __init__(self, documents):
        self.documents = documents

    def find(self, query, projection=None):
        return Cursor([row for row in self.documents if matches(row, query)])

    async def distinct(self, key, query):
        return list({row[key] for row in self.documents if matches(row, query)})

    async def count_documents(self, query):
        return sum(matches(row, query) for row in self.documents)

    def aggregate(self, pipeline):
        rows = [row for row in self.documents if matches(row, pipeline[0]["$match"])]
        return Cursor([{"avg": sum(row["response_time_seconds"] for row in rows) / len(rows)}] if rows else [])


@pytest.fixture(scope="module")
def handler():
    path = Path(__file__).resolve().parents[1] / "news-handler" / "main.py"
    spec = importlib.util.spec_from_file_location("isolation_news_handler", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest_asyncio.fixture
async def clients(handler, monkeypatch):
    orders = [
        {"order_id": owner, "client_id": f"user_{owner}", "text": f"private-{owner}",
         "assertions": [{"idAssertion": "1", "text": f"assertion-{owner}", "categoryId": 1}]}
        for owner in ("alpha", "beta")
    ]
    validations = [
        {"order_id": owner, "idValidator": "validator", "idAssertion": "1",
         "execution_status": "COMPLETED", "response_time_seconds": duration,
         "payload": {"description": f"private-{owner}"}}
        for owner, duration in (("alpha", 2), ("beta", 10), ("orphan", 50))
    ]
    events = [{"order_id": row["order_id"], "action": "light_validation_request",
               "payload": {"validator_id": "validator"}} for row in validations]
    monkeypatch.setattr(handler, "orders_collection", Collection(orders))
    monkeypatch.setattr(handler, "validations_collection", Collection(validations))
    monkeypatch.setattr(handler, "events_collection", Collection(events))
    monkeypatch.setattr(handler, "validators_cache", {"validator": {"validator": "validator", "config": {}}})

    async def verified_claims(request: Request):
        subject = request.headers.get("x-test-sub")
        if subject is None:
            raise HTTPException(401)
        return {"sub": subject, "realm_access": {"roles": ["trust-admin"] if request.headers.get("x-test-admin") else []}}

    monkeypatch.setitem(gateway.app.dependency_overrides, gateway.get_current_user, verified_claims)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=handler.app), base_url="http://handler") as internal:
        async def forward(request, target_url):
            url = urlsplit(target_url)
            return await internal.get(url.path + "?" + url.query)

        async def proxy(request, target_url):
            from fastapi.responses import JSONResponse
            response = await forward(request, target_url)
            return JSONResponse(response.json(), status_code=response.status_code)

        monkeypatch.setattr(gateway, "proxy_request", proxy)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url="http://gateway") as public:
            yield public, internal


PATH = "/validators/cache/validator/validations"


@pytest.mark.asyncio
@pytest.mark.parametrize("owner,duration", [("alpha", 2), ("beta", 10)])
@pytest.mark.parametrize("admin", [False, True])
async def test_only_own_validations_text_links_and_statistics(clients, owner, duration, admin):
    public, _ = clients
    response = await public.get(PATH, headers={"x-test-sub": owner, **({"x-test-admin": "yes"} if admin else {})},
                                params={"include_validations": "true", "include_order_link": "true",
                                        "client_id": "user_other", "admin": "true"})
    assert response.status_code == 200
    body = response.json()
    assert [v["order_id"] for v in body["validations"]] == [owner]
    assert body["validations"][0]["order_text"] == f"private-{owner}"
    assert body["validations"][0]["assertion_text"] == f"assertion-{owner}"
    assert body["validations"][0]["order_link"] == f"/orders/{owner}"
    assert body["stats"] == {"requests_sent": 1, "successful_responses": 1, "avg_response_time_seconds": duration}
    assert "orphan" not in response.text
    assert f"private-{'beta' if owner == 'alpha' else 'alpha'}" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("details", [False, True])
async def test_owner_without_orders_gets_empty_result_and_zero_stats(clients, details):
    response = await clients[0].get(PATH, headers={"x-test-sub": "empty"}, params={"include_validations": str(details).lower()})
    assert response.status_code == 200
    assert response.json()["validations"] == []
    assert response.json()["stats"] == {"requests_sent": 0, "successful_responses": 0, "avg_response_time_seconds": None}


@pytest.mark.asyncio
async def test_no_details_does_not_expose_global_statistics(clients):
    response = await clients[0].get(PATH, headers={"x-test-sub": "alpha"})
    assert response.status_code == 200
    assert response.json()["validations"] == []
    assert response.json()["stats"]["avg_response_time_seconds"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("scope,status", [(None, 422), ("", 422), ("   ", 400)])
async def test_internal_endpoint_requires_scope_even_with_admin_flag(clients, scope, status):
    params = {"include_validations": "true", "admin": "true"}
    if scope is not None:
        params["client_id"] = scope
    response = await clients[1].get(PATH, params=params)
    assert response.status_code == status


@pytest.mark.asyncio
async def test_internal_admin_parameter_cannot_disable_owner_filter(clients):
    response = await clients[1].get(PATH, params={"client_id": "user_alpha", "admin": "true", "include_validations": "true"})
    assert response.status_code == 200
    assert [v["order_id"] for v in response.json()["validations"]] == ["alpha"]


@pytest.mark.asyncio
@pytest.mark.parametrize("subject", [None, "", "   "])
async def test_missing_authenticated_identity_is_rejected(clients, subject):
    headers = {} if subject is None else {"x-test-sub": subject}
    response = await clients[0].get(PATH, headers=headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_provider_and_model_cannot_inject_scope(clients, monkeypatch):
    captured = []
    async def proxy(request, target_url):
        captured.append(parse_qs(urlsplit(target_url).query))
        return {"ok": True}
    monkeypatch.setattr(gateway, "proxy_request", proxy)
    attack = "test&client_id=user_beta&admin=true"
    response = await clients[0].get(PATH, headers={"x-test-sub": "alpha"}, params={"provider": attack, "model": attack})
    assert response.status_code == 200
    assert captured[0]["client_id"] == ["user_alpha"]
    assert "admin" not in captured[0]
    assert captured[0]["provider"] == [attack]
    assert captured[0]["model"] == [attack]
