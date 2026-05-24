from typing import Any, Dict

import httpx
from fastapi import HTTPException


async def fetch_client_quotas(admin_url: str, client_id: str) -> Dict[str, Any]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{admin_url}/clients/{client_id}")
        if resp.status_code == 404:
            raise HTTPException(status_code=403, detail="Client quotas not found")
        resp.raise_for_status()
        return resp.json()


async def update_client_consumed(admin_url: str, client_id: str, field: str, new_value: int) -> None:
    async with httpx.AsyncClient() as client:
        payload = {"consumed": {field: new_value}}
        resp = await client.patch(f"{admin_url}/clients/{client_id}", json=payload)
        resp.raise_for_status()
