"""Immutable, content-addressed document snapshots for audit and reuse."""

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from common.search.normalization import normalize_url


SNAPSHOT_SCHEMA = "evidence-document-snapshot-v1"
MAX_TEXT_BYTES = 8 * 1024 * 1024


def snapshot_identity(url: str, method: str, provider: str | None, text: str) -> tuple[str, str]:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    identity = hashlib.sha256("\n".join((SNAPSHOT_SCHEMA, normalize_url(url), method, provider or "", digest)).encode()).hexdigest()
    return identity, digest


async def save_snapshot(collection: Any, *, url: str, method: str, provider: str | None,
                        text: str, resolved_url: str | None, received_at: str | None,
                        freshness_status: str, ttl_seconds: int) -> str | None:
    if collection is None or not text or len(text.encode("utf-8")) > MAX_TEXT_BYTES or ttl_seconds <= 0:
        return None
    identity, digest = snapshot_identity(url, method, provider, text)
    now = datetime.now(timezone.utc)
    await collection.update_one(
        {"_id": identity},
        {"$setOnInsert": {"_id": identity, "schema_version": SNAPSHOT_SCHEMA,
                          "url": normalize_url(url), "method": method, "provider": provider,
                          "text": text, "text_sha256": digest, "resolved_url": resolved_url,
                          "received_at": received_at, "freshness_status": freshness_status,
                          "stored_at": now},
         "$max": {"expires_at": now + timedelta(seconds=ttl_seconds)}},
        upsert=True,
    )
    return identity


async def load_snapshot(collection: Any, *, url: str, provider: str | None,
                        max_age_seconds: int, require_known_freshness: bool) -> dict[str, Any] | None:
    if collection is None or max_age_seconds <= 0:
        return None
    now = datetime.now(timezone.utc)
    allowed = {"$or": [{"method": "direct_fetch"},
                       {"method": "provider_extract", "provider": provider}]}
    row = await collection.find_one(
        {"url": normalize_url(url), "expires_at": {"$gt": now}, **allowed},
        sort=[("stored_at", -1)],
    )
    if not row or row.get("schema_version") != SNAPSHOT_SCHEMA:
        return None
    stored_at = row.get("stored_at")
    if not isinstance(stored_at, datetime):
        return None
    if stored_at.tzinfo is None:
        stored_at = stored_at.replace(tzinfo=timezone.utc)
    if not 0 <= (now - stored_at).total_seconds() <= max_age_seconds:
        return None
    text = row.get("text")
    if not isinstance(text, str):
        return None
    identity, digest = snapshot_identity(url, row.get("method") or "", row.get("provider"), text)
    if identity != row.get("_id") or digest != row.get("text_sha256"):
        return None
    if require_known_freshness and row.get("freshness_status") != "OBSERVED_NOW":
        return None
    return row
