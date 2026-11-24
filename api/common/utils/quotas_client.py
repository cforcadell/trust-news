import os
import hashlib
import json
import re
from typing import Any, Dict
from urllib.parse import quote

import httpx
from fastapi import HTTPException
from common.security.engine import internal_headers

_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9_-]{8,96}\Z")


def integration_quota_payload(key: str | None, field: str, body: dict,
                              client_id: str, operation_type: str) -> dict:
    if not key or not _IDEMPOTENCY_KEY.fullmatch(key):
        raise HTTPException(status_code=400, detail="Valid Idempotency-Key required for integration")
    canonical = json.dumps({"client_id": client_id, "field": field,
                            "operation_type": operation_type, "body": body},
                           sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return {"field": field, "operation_id": key,
            "request_hash": hashlib.sha256(canonical).hexdigest(), "cost": 1}


async def integration_quota_operation(admin_url: str, client_id: str, step: str,
                                      payload: dict, user_token: str) -> dict:
    if step not in {"reserve", "consume", "release"}:
        raise ValueError("Unknown integration quota operation")
    if not admin_url.startswith("https://") or not user_token:
        raise HTTPException(status_code=503, detail="Protected integration quota unavailable")
    path = f"{admin_url.rstrip('/')}/internal/integrations/quotas/{quote(client_id, safe='')}/{step}"
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=os.getenv("S03_CA_FILE") or True) as client:
            response = await client.post(path, json=payload,
                                         headers=await internal_headers("assermetry-admin", user_token))
        if response.status_code in (400, 403, 409, 429):
            raise HTTPException(status_code=response.status_code, detail="Integration quota denied")
        response.raise_for_status()
        result = response.json()
        state = result.get("state")
        if state not in {"reserved", "consumed", "released"}:
            raise ValueError("Invalid quota state")
        return result
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Integration quota unavailable") from exc


async def fetch_client_quotas(admin_url: str, client_id: str, *, order_id: str | None = None,
                              user_token: str | None = None) -> Dict[str, Any]:
    enabled = os.getenv("S03_ENABLED", "false").lower() == "true"
    if enabled and not admin_url.startswith("https://"):
        raise HTTPException(status_code=503, detail="Protected Admin URL requires HTTPS")
    path = "internal/quotas" if enabled else "clients"
    async with httpx.AsyncClient(timeout=10.0, verify=os.getenv("S03_CA_FILE") or True) as client:
        resp = await client.get(f"{admin_url}/{path}/{quote(client_id, safe='')}",
                                params={"order_id": order_id} if enabled and order_id else None,
                                headers=await internal_headers("assermetry-admin", user_token))
        if resp.status_code == 404:
            raise HTTPException(status_code=403, detail="Client quotas not found")
        resp.raise_for_status()
        return resp.json()


async def update_client_consumed(admin_url: str, client_id: str, field: str, new_value: int, *,
                                 order_id: str | None = None, user_token: str | None = None) -> None:
    enabled = os.getenv("S03_ENABLED", "false").lower() == "true"
    if enabled and not admin_url.startswith("https://"):
        raise HTTPException(status_code=503, detail="Protected Admin URL requires HTTPS")
    encoded = quote(client_id, safe="")
    path = f"internal/quotas/{encoded}/consumed" if enabled else f"clients/{encoded}"
    payload = {"field": field, "value": new_value} if enabled else {"consumed": {field: new_value}}
    async with httpx.AsyncClient(timeout=10.0, verify=os.getenv("S03_CA_FILE") or True) as client:
        resp = await client.patch(f"{admin_url}/{path}", json=payload,
                                  params={"order_id": order_id} if enabled and order_id else None,
                                  headers=await internal_headers("assermetry-admin", user_token))
        resp.raise_for_status()
