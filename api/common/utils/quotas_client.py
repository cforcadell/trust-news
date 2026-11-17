import os
from typing import Any, Dict
from urllib.parse import quote

import httpx
from fastapi import HTTPException
from common.security.engine import internal_headers


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
