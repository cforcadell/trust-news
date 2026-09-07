import asyncio
import importlib.util
import os
import sys
import types

import pytest


def load_news_handler_module():
    api_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if api_root not in sys.path:
        sys.path.insert(0, api_root)
    path = os.path.join(api_root, "news-handler", "main.py")
    spec = importlib.util.spec_from_file_location("news_handler_main", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_minimal_document_for_order_shape():
    module = load_news_handler_module()
    document = module.minimal_document_for_order(
        text="Este es un texto de prueba",
        assertions=[{"idAssertion": "a1", "text": "Prueba", "categoryId": 1}],
    )

    assert document == {
        "text": "Este es un texto de prueba",
        "assertions": [{"idAssertion": "a1", "text": "Prueba", "categoryId": 1}],
    }


def test_start_light_flow_updates_order_with_minimal_document(monkeypatch):
    module = load_news_handler_module()
    calls = {}

    async def fake_update_order(order_id, update):
        calls["order_id"] = order_id
        calls["update"] = update

    async def fake_dispatch(order_id, text, assertions_document, client_id=None):
        calls["dispatched"] = True
        calls["dispatch_args"] = {
            "order_id": order_id,
            "text": text,
            "client_id": client_id,
        }

    def fake_hash_text_to_multihash(text):
        return types.SimpleNamespace(digest="fake-digest")

    monkeypatch.setattr(module, "update_order", fake_update_order)
    monkeypatch.setattr(module, "dispatch_light_validation_requests", fake_dispatch)
    monkeypatch.setattr(module, "hash_text_to_multihash", fake_hash_text_to_multihash)

    assertions_document = module.build_assertions_document_v2(
        text="Texto de prueba",
        assertions=[{"idAssertion": "1", "text": "Aserción de prueba", "categoryId": 1}],
        mode=module.ValidationMode.LIGHT,
        provider="test",
    )

    asyncio.run(module.start_light_flow("order-123", "Texto de prueba", assertions_document, client_id="client-1"))

    assert calls["order_id"] == "order-123"
    assert calls["dispatched"] is True

    assert "$set" in calls["update"]
    order_update = calls["update"]["$set"]

    assert order_update["validation_mode"] == module.ValidationMode.LIGHT.value
    assert order_update["status"] == "DOCUMENT_CREATED"
    assert order_update["cid"] is None
    assert order_update["tx_hash"] is None

    assert order_update["document"]["text"] == "Texto de prueba"
    assert len(order_update["document"]["assertions"]) == 1
    assertion_item = order_update["document"]["assertions"][0]
    assert assertion_item["idAssertion"] == "1"
    assert assertion_item["text"] == "Aserción de prueba"
    assert assertion_item["categoryId"] == 1
    assert "assertion_id" not in assertion_item
    assert "assertion_index" not in assertion_item

    assert "assertions_document" not in order_update


def test_legacy_validation_weight_fallback_is_marked(monkeypatch):
    module = load_news_handler_module()
    order = {
        "validations": {
            "1": {
                "legacy-validator": {
                    "approval": "TRUE",
                    "execution_status": "COMPLETED",
                }
            }
        }
    }
    monkeypatch.setattr(
        module,
        "get_cached_validator_config",
        lambda _: {"validator_type": 3, "reputation": 0.8, "config": {"name": "Legacy"}},
    )

    module.attach_validator_config_snapshots(order)

    validation = order["validations"]["1"]["legacy-validator"]
    assert validation["legacy_dynamic_weight"] is True
    assert validation["validator_config"]["validator_type"] == 3


def test_validation_log_persists_frozen_weight_fields(monkeypatch):
    module = load_news_handler_module()
    inserted = {}

    class FakeCollection:
        async def insert_one(self, document):
            inserted.update(document)

    monkeypatch.setattr(module, "validations_collection", FakeCollection())
    snapshot = module.validation_weight_snapshot(
        {"validator_type": 3, "reputation": 0.8},
        {"RAG_EVIDENCE_VALIDATION": 0.75},
    )
    asyncio.run(
        module.log_validation(
            "order-1",
            "post-1",
            "assertion-1",
            "validator-1",
            module.Validacion.TRUE,
            "0x123",
            snapshot,
            module.ValidationExecutionStatus.COMPLETED,
        )
    )

    assert inserted["validator_type"] == "RAG_EVIDENCE_VALIDATION"
    assert inserted["validator_type_weight"] == 0.75
    assert inserted["reputation_at_validation"] == 0.8
    assert inserted["effective_weight"] == pytest.approx(0.6)
    assert inserted["weights_policy_version"] == "validator-weights-v1"
    assert inserted["legacy_dynamic_weight"] is False
