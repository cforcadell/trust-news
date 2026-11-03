"""Safe client for the non-secret LLM runtime overrides held by Admin.

The endpoint is only reachable through a ClusterIP service.  It deliberately
returns provider, model, temperature and version only; credentials always stay
in the process environment populated from Kubernetes Secrets.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx


async def fetch_llm_runtime_override(
    admin_url: str,
    config_id: str,
    logger: logging.Logger,
) -> dict[str, Any] | None:
    """Return a persisted desired override, or ``None`` when unavailable.

    Startup must remain available when Admin/Mongo has not started yet, so all
    failures intentionally fall back to the deployment defaults and are logged
    without response bodies (which could contain untrusted data).
    """
    if not admin_url or not config_id:
        return None
    url = f"{admin_url.rstrip('/')}/internal/llm/overrides/{quote(config_id, safe=':')}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        desired = payload.get("desired") if isinstance(payload, dict) else None
        return desired if isinstance(desired, dict) else None
    except Exception as exc:
        logger.warning("LLM runtime override unavailable; using deployment defaults: %s", exc.__class__.__name__)
        return None
