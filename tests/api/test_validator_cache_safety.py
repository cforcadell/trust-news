import asyncio
import importlib.util
import os
import sys

import pytest


def load_news_handler_module():
    api_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "api"))
    if api_root not in sys.path:
        sys.path.insert(0, api_root)
    path = os.path.join(api_root, "news-handler", "main.py")
    spec = importlib.util.spec_from_file_location("validator_cache_news_handler", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validator(identifier, *, name=None, updated_at=None, source=None):
    item = {
        "validator": identifier,
        "categories": [1],
        "validator_type": 1,
        "reputation": 1.0,
        "config": {"name": name or identifier, "status": 1, "type": 1},
    }
    if updated_at is not None:
        item["updated_at"] = updated_at
    if source is not None:
        item["source"] = source
    return item


@pytest.mark.asyncio
async def test_empty_refresh_preserves_last_valid_cache_and_light_selection(monkeypatch):
    module = load_news_handler_module()
    cached = {f"validator-{index}": validator(f"validator-{index}") for index in range(3)}
    module.validators_cache = cached

    async def empty_snapshot():
        return []

    monkeypatch.setattr(module, "fetch_validators_from_chain", empty_snapshot)

    assert await module.load_validators_cache_from_chain() is False
    assert module.validators_cache is cached
    assert len(module.get_light_validators_for_category(1)) == 3


@pytest.mark.asyncio
async def test_failed_or_unusable_refresh_preserves_last_valid_cache(monkeypatch):
    module = load_news_handler_module()
    cached = {"validator-a": validator("validator-a")}
    module.validators_cache = cached

    async def failed_snapshot():
        raise RuntimeError("news-chain unavailable")

    monkeypatch.setattr(module, "fetch_validators_from_chain", failed_snapshot)
    assert await module.load_validators_cache_from_chain() is False
    assert module.validators_cache is cached

    async def unusable_snapshot():
        return [{"config": {"name": "missing validator id"}}, None]

    monkeypatch.setattr(module, "fetch_validators_from_chain", unusable_snapshot)
    assert await module.load_validators_cache_from_chain() is False
    assert module.validators_cache is cached


@pytest.mark.asyncio
async def test_valid_refresh_is_atomic_and_preserves_local_metrics(monkeypatch):
    module = load_news_handler_module()
    previous = validator("validator-a", name="old")
    previous["metrics_reset_at"] = "2026-10-06T10:00:00+00:00"
    old_cache = {"validator-a": previous, "validator-removed": validator("validator-removed")}
    module.validators_cache = old_cache

    async def valid_snapshot():
        return [validator("VALIDATOR-A", name="new"), validator("validator-b")]

    monkeypatch.setattr(module, "fetch_validators_from_chain", valid_snapshot)

    assert await module.load_validators_cache_from_chain() is True
    assert module.validators_cache is not old_cache
    assert set(module.validators_cache) == {"validator-a", "validator-b"}
    assert module.validators_cache["validator-a"]["config"]["name"] == "new"
    assert module.validators_cache["validator-a"]["metrics_reset_at"] == "2026-10-06T10:00:00+00:00"


@pytest.mark.asyncio
async def test_event_arriving_during_refresh_is_not_overwritten(monkeypatch):
    module = load_news_handler_module()
    module.validators_cache = {
        "validator-a": validator(
            "validator-a", name="initial", updated_at="2026-10-06T10:00:00+00:00"
        )
    }
    fetch_started = asyncio.Event()
    release_fetch = asyncio.Event()

    async def stale_snapshot():
        fetch_started.set()
        await release_fetch.wait()
        return [validator("validator-a", name="stale-chain")]

    monkeypatch.setattr(module, "fetch_validators_from_chain", stale_snapshot)
    refresh_task = asyncio.create_task(module.load_validators_cache_from_chain())
    await fetch_started.wait()

    await module.update_validator_cache_from_event({
        "validator": "validator-a",
        "config": {"name": "event-update", "status": 1, "type": 1},
        "categories": [1],
        "timestamp": "2026-10-06T11:00:00+00:00",
    })
    release_fetch.set()

    assert await refresh_task is True
    assert module.validators_cache["validator-a"]["config"]["name"] == "event-update"
    assert module.validators_cache["validator-a"]["_cache_origin"] == "validator-event"


@pytest.mark.asyncio
async def test_event_missing_from_snapshot_is_preserved_until_chain_catches_up(monkeypatch):
    module = load_news_handler_module()
    event_validator = validator(
        "validator-event", name="event-only", updated_at="2026-10-06T11:00:00+00:00"
    )
    event_validator["_cache_origin"] = "validator-event"
    module.validators_cache = {"validator-event": event_validator}

    async def snapshot_without_event():
        return [validator("validator-chain")]

    monkeypatch.setattr(module, "fetch_validators_from_chain", snapshot_without_event)

    assert await module.load_validators_cache_from_chain() is True
    assert set(module.validators_cache) == {"validator-chain", "validator-event"}


@pytest.mark.asyncio
async def test_event_can_initialize_cache_when_news_chain_is_degraded(monkeypatch):
    module = load_news_handler_module()
    module.validators_cache = {}

    async def empty_snapshot():
        return []

    monkeypatch.setattr(module, "fetch_validators_from_chain", empty_snapshot)
    await module.update_validator_cache_from_event({
        "validator": "validator-event",
        "config": {"name": "event-only", "status": 1, "type": 1},
        "categories": [1],
    })

    assert set(module.validators_cache) == {"validator-event"}
    assert len(module.get_light_validators_for_category(1)) == 1
    assert "_cache_origin" not in module.validator_summary_for_ui(module.validators_cache["validator-event"])
