from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2] / "api" / "evidence-search"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.acquisition import ExtractionPolicy, acquire_document
from app.document_store import load_snapshot, save_snapshot


class MemorySnapshots:
    def __init__(self):
        self.rows = {}

    async def update_one(self, selector, changes, upsert=False):
        row = self.rows.setdefault(selector["_id"], changes["$setOnInsert"].copy())
        row["expires_at"] = changes["$max"]["expires_at"]

    async def find_one(self, selector, sort=None):
        url = selector["url"]
        now = selector["expires_at"]["$gt"]
        rows = [row for row in self.rows.values() if row["url"] == url and row["expires_at"] > now
                and (row["method"] == "direct_fetch"
                     or row["method"] == "provider_extract" and row["provider"] == selector["$or"][1]["provider"])]
        return max(rows, key=lambda row: row["stored_at"], default=None)


@pytest.mark.asyncio
async def test_document_snapshot_is_immutable_versioned_and_verified():
    collection = MemorySnapshots()
    url = "https://example.org/report"
    first = await save_snapshot(collection, url=url, method="direct_fetch", provider=None,
                                text="First document " * 12, resolved_url=url,
                                received_at="2026-10-28T12:00:00+00:00", freshness_status="OBSERVED_NOW",
                                ttl_seconds=3600)
    again = await save_snapshot(collection, url=url, method="direct_fetch", provider=None,
                                text="First document " * 12, resolved_url=url,
                                received_at="2026-10-28T12:00:00+00:00", freshness_status="OBSERVED_NOW",
                                ttl_seconds=3600)
    second = await save_snapshot(collection, url=url, method="direct_fetch", provider=None,
                                 text="Second document " * 12, resolved_url=url,
                                 received_at="2026-10-28T12:01:00+00:00", freshness_status="OBSERVED_NOW",
                                 ttl_seconds=3600)
    assert first == again and second != first
    assert len(collection.rows) == 2
    loaded = await load_snapshot(collection, url=url, provider=None, max_age_seconds=3600,
                                 require_known_freshness=True)
    assert loaded["_id"] in {first, second}
    collection.rows[loaded["_id"]]["text"] = "tampered"
    assert await load_snapshot(collection, url=url, provider=None, max_age_seconds=3600,
                               require_known_freshness=True) is None


@pytest.mark.asyncio
async def test_cached_document_preserves_original_freshness_timestamp():
    collection = MemorySnapshots()
    url = "https://example.org/report"
    original = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    await save_snapshot(collection, url=url, method="direct_fetch", provider=None,
                        text="Official report content. " * 12, resolved_url=url,
                        received_at=original, freshness_status="OBSERVED_NOW", ttl_seconds=3600)

    async def no_direct_fetch(*args, **kwargs):
        raise AssertionError("Cache hit should avoid a new HTTP request")

    async def cached(**kwargs):
        return await load_snapshot(collection, **kwargs)

    result = await acquire_document(
        {"url": url}, url, ExtractionPolicy(mode="DIRECT", max_content_age_seconds=3600,
                                             require_known_freshness=True), no_direct_fetch,
        timeout=1, user_agent="test", load_cached=cached,
    )
    assert result.method == "document_cache"
    assert result.freshness_status == "CACHED_KNOWN_AGE"
    assert result.source_fetched_at == original
    assert result.snapshot_id in collection.rows
