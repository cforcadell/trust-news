import asyncio
import importlib.util
import os
import sys
import types

import pytest


def load_news_handler_module():
    api_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "api"))
    if api_root not in sys.path:
        sys.path.insert(0, api_root)
    path = os.path.join(api_root, "news-handler", "main.py")
    spec = importlib.util.spec_from_file_location("news_handler_main", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assertion_payload():
    return {
        "idAssertion": "1",
        "text": "El paro descendio en Espana.",
        "categoryId": 1,
        "topic_code": "EMPLOYMENT",
        "evidence_kind": "STATISTICAL_DATA",
        "context": {
            "locations": [], "entities": [], "temporal_context": [], "language": "es",
            "jurisdiction": {"scope": "COUNTRY", "country_code": "ES"},
        },
    }


def test_generated_payload_requires_the_canonical_document():
    module = load_news_handler_module()
    document = module.build_assertions_document_v2(
        text="Este es un texto de prueba", assertions=[assertion_payload()],
        mode=module.ValidationMode.LIGHT, provider="test",
    )
    response = module.AssertionsGeneratedResponse(
        action="assertions_generated", order_id="order-1",
        payload={"assertions_document": document},
    )
    assert response.payload.assertions_document.schema_version == "assertions-document-v2"

    with pytest.raises(Exception):
        module.AssertionsGeneratedResponse(
            action="assertions_generated", order_id="order-1",
            payload={"text": "legacy", "assertions": []},
        )


def test_start_light_flow_stores_the_full_protocol_document(monkeypatch):
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
        assertions=[assertion_payload()],
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

    assert order_update["document"]["schema_version"] == "assertions-document-v2"
    assert order_update["document"]["post"]["original_text"] == "Texto de prueba"
    assert len(order_update["document"]["assertions"]) == 1
    assertion_item = order_update["document"]["assertions"][0]
    assert assertion_item["assertion_id"] == 1
    assert assertion_item["text"] == "El paro descendio en Espana."
    assert assertion_item["categoryId"] == 1
    assert assertion_item["topic_code"] == "EMPLOYMENT"


def test_blockchain_request_publishes_only_the_canonical_cid(monkeypatch):
    module = load_news_handler_module()
    calls = {}

    class Producer:
        async def send_and_wait(self, topic, payload):
            calls["topic"] = topic
            calls["payload"] = payload

    async def fake_log_event(order_id, action, topic, payload):
        calls["event"] = {
            "order_id": order_id,
            "action": action,
            "topic": topic,
            "payload": payload,
        }

    monkeypatch.setattr(module, "producer", Producer())
    monkeypatch.setattr(module, "log_event", fake_log_event)

    request = asyncio.run(module.handle_blockchain_request("order-123", "QmCID"))

    assert request.payload.cid == "QmCID"
    assert request.payload.schema_version == "register-blockchain-v2"
    assert "text" not in request.payload.model_dump()
    assert "assertions" not in request.payload.model_dump()
    assert calls["event"]["payload"]["cid"] == "QmCID"


def test_blockchain_registered_merges_assignments_with_canonical_document(monkeypatch):
    module = load_news_handler_module()
    updates = []
    document = module.build_assertions_document_v2(
        text="Texto de prueba",
        assertions=[assertion_payload()],
        mode=module.ValidationMode.BLOCKCHAIN,
        provider="test",
    ).model_dump(mode="json")

    async def fake_get_order_doc(order_id):
        return {"order_id": order_id, "document": document, "assertions": []}

    async def fake_update_order(order_id, update):
        updates.append(update)

    async def fake_log_event(*args, **kwargs):
        return None

    monkeypatch.setattr(module, "get_order_doc", fake_get_order_doc)
    monkeypatch.setattr(module, "update_order", fake_update_order)
    monkeypatch.setattr(module, "log_event", fake_log_event)

    asyncio.run(module.process_kafka_message({
        "action": "blockchain_registered",
        "order_id": "order-123",
        "payload": {
            "postId": "7",
            "cid": "QmCID",
            "hash_text": "0xabc",
            "tx_hash": "0xdef",
            "assertions": [{
                "idAssertion": "1",
                "assertion_index": 0,
                "categoryId": 1,
                "validatorAddresses": [{"address": "0x123"}],
            }],
        },
    }))

    persisted = updates[-1]["$set"]
    assert persisted["post_id"] == 7
    assert persisted["status"] == "VALIDATION_PENDING"
    assert persisted["validators_pending"] == 1
    assert persisted["validators"][0]["text"] == "El paro descendio en Espana."
    assert persisted["validators"][0]["topic_code"] == "EMPLOYMENT"


def test_blockchain_registration_failure_is_terminal_and_auditable(monkeypatch):
    module = load_news_handler_module()
    updates = []

    async def fake_update_order(order_id, update):
        updates.append(update)

    async def fake_log_event(*args, **kwargs):
        return None

    monkeypatch.setattr(module, "update_order", fake_update_order)
    monkeypatch.setattr(module, "log_event", fake_log_event)

    asyncio.run(module.process_kafka_message({
        "action": "blockchain_registration_failed",
        "order_id": "order-123",
        "payload": {
            "stage": "IPFS_READ",
            "code": "BLOCKCHAIN_REGISTRATION_FAILED",
            "message": "missing document",
            "retryable": True,
        },
    }))

    persisted = updates[-1]["$set"]
    assert persisted["status"] == "BLOCKCHAIN_ERROR"
    assert persisted["blockchain_error"]["stage"] == "IPFS_READ"
    assert persisted["blockchain_error"]["retryable"] is True


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
