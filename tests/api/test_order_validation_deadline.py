import asyncio
import copy
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace


def load_handler():
    import sys

    api_root = Path(__file__).resolve().parents[2] / "api"
    if str(api_root) not in sys.path:
        sys.path.insert(0, str(api_root))
    spec = importlib.util.spec_from_file_location("news_handler_deadline_test", api_root / "news-handler" / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Orders:
    def __init__(self, order):
        self.order = copy.deepcopy(order)

    async def find_one(self, query):
        return copy.deepcopy(self.order) if query.get("order_id") == self.order["order_id"] else None

    async def update_one(self, query, update):
        order = self.order
        if any(
            order.get(key) != value
            for key, value in query.items()
            if key != "validation_deadline_at"
        ):
            return SimpleNamespace(modified_count=0)
        deadline_filter = query.get("validation_deadline_at")
        if deadline_filter:
            deadline = order.get("validation_deadline_at")
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            if "$lte" in deadline_filter and deadline > deadline_filter["$lte"]:
                return SimpleNamespace(modified_count=0)
            if "$gt" in deadline_filter and deadline <= deadline_filter["$gt"]:
                return SimpleNamespace(modified_count=0)
        order.update(copy.deepcopy(update["$set"]))
        return SimpleNamespace(modified_count=1)


def pending_order(minutes_ago=31):
    now = datetime.now(timezone.utc)
    return {
        "order_id": "order-1",
        "status": "VALIDATION_PENDING",
        "validation_revision": 0,
        "validation_deadline_at": now - timedelta(minutes=minutes_ago),
        "validators": [{"idAssertion": "1", "validatorAddresses": ["a", "b"]}],
        "validations": {"1": {"a": {"execution_status": "COMPLETED", "approval": "TRUE"}}},
        "validators_pending": 1,
    }


def test_expired_order_keeps_real_votes_and_rejects_late_response():
    module = load_handler()
    orders = Orders(pending_order())
    module.orders_collection = orders

    assert asyncio.run(module.expire_validation_order("order-1")) is True
    assert orders.order["status"] == "VALIDATED_AUTOMATICALLY"
    assert orders.order["validations"]["1"].keys() == {"a"}
    assert orders.order["unanswered_validations"] == [{"idAssertion": "1", "validator_id": "b"}]
    assert orders.order["validators_pending"] == 0
    assert asyncio.run(module.persist_validation_result("order-1", "1", "b", {"execution_status": "COMPLETED"})) is None
    assert asyncio.run(module.expire_validation_order("order-1")) is False


def test_last_response_closes_normally_and_cannot_be_expired():
    module = load_handler()
    orders = Orders(pending_order(minutes_ago=-1))
    module.orders_collection = orders

    status = asyncio.run(module.persist_validation_result("order-1", "1", "b", {"execution_status": "ERROR"}))
    assert status == "VALIDATED_WITH_ERRORS"
    assert orders.order["validators_pending"] == 0
    assert asyncio.run(module.expire_validation_order("order-1")) is False


def test_response_after_deadline_is_not_accepted_before_the_sweep():
    module = load_handler()
    orders = Orders(pending_order())
    module.orders_collection = orders

    assert asyncio.run(module.persist_validation_result("order-1", "1", "b", {"execution_status": "COMPLETED"})) is None
    assert orders.order["validations"]["1"].keys() == {"a"}


def test_automatic_closure_audit_event_is_idempotent():
    module = load_handler()
    orders = Orders(pending_order())
    module.orders_collection = orders

    class Events:
        def __init__(self):
            self.rows = {}

        async def update_one(self, query, update, upsert=False):
            self.rows.setdefault(query["event_key"], update["$setOnInsert"])

    events = Events()
    module.events_collection = events
    assert asyncio.run(module.expire_validation_order("order-1"))
    asyncio.run(module.record_automatic_closure_event(orders.order))
    asyncio.run(module.record_automatic_closure_event(orders.order))

    assert len(events.rows) == 1
    assert orders.order["closure_event_recorded"] is True


def test_last_response_and_deadline_cannot_overwrite_each_other():
    module = load_handler()
    order = pending_order(minutes_ago=-1)

    class RacingOrders(Orders):
        async def update_one(self, query, update):
            await asyncio.sleep(0)
            return await super().update_one(query, update)

    orders = RacingOrders(order)
    module.orders_collection = orders

    async def race():
        await asyncio.gather(
            module.expire_validation_order("order-1", order["validation_deadline_at"] + timedelta(seconds=1)),
            module.persist_validation_result("order-1", "1", "b", {"execution_status": "COMPLETED"}),
        )

    asyncio.run(race())
    assert orders.order["status"] in {"VALIDATED", "VALIDATED_AUTOMATICALLY"}
    assert ("b" in orders.order["validations"]["1"]) == (orders.order["status"] == "VALIDATED")


def test_deadline_does_not_close_an_order_early():
    module = load_handler()
    orders = Orders(pending_order(minutes_ago=-1))
    module.orders_collection = orders

    assert asyncio.run(module.expire_validation_order("order-1")) is False
    assert orders.order["status"] == "VALIDATION_PENDING"


def test_legacy_order_without_deadline_is_not_expired_and_can_finish_normally():
    module = load_handler()
    order = pending_order()
    order.pop("validation_deadline_at")
    order.pop("validation_revision")
    orders = Orders(order)
    module.orders_collection = orders

    assert asyncio.run(module.expire_validation_order("order-1")) is False
    assert asyncio.run(module.persist_validation_result("order-1", "1", "b", {"execution_status": "COMPLETED"})) == "VALIDATED"
    assert orders.order["validation_revision"] == 1
    assert orders.order["validators_pending"] == 0


def test_naive_utc_date_from_mongo_can_be_expired_and_audited():
    module = load_handler()
    order = pending_order()
    order["validation_deadline_at"] = order["validation_deadline_at"].replace(tzinfo=None)
    orders = Orders(order)
    module.orders_collection = orders

    class Events:
        def __init__(self):
            self.rows = {}

        async def update_one(self, query, update, upsert=False):
            self.rows.setdefault(query["event_key"], update["$setOnInsert"])

    events = Events()
    module.events_collection = events
    assert asyncio.run(module.expire_validation_order("order-1"))
    asyncio.run(module.record_automatic_closure_event(orders.order))
    asyncio.run(module.record_late_validation("order-1", "1", "b"))
    asyncio.run(module.record_late_validation("order-1", "1", "b"))
    assert len(events.rows) == 2
    assert events.rows["order-1:validation_deadline_exceeded"]["payload"]["received_validations_count"] == 1
    assert events.rows["order-1:late_validation:1:b"]["action"] == "validation_response_late"


def test_gateway_adds_one_policy_header_to_both_publish_routes(monkeypatch):
    import gateway.main as gateway

    calls = []

    async def proxy(request, target_url, extra_headers=None):
        calls.append((target_url, extra_headers))
        return None

    monkeypatch.setattr(gateway, "proxy_request", proxy)
    identity = {"sub": "subject", "client_id": "client"}
    asyncio.run(gateway.proxy_publish_new(SimpleNamespace(), auth_payload=identity))
    asyncio.run(gateway.proxy_publish_with_assertions(SimpleNamespace(), auth_payload=identity))

    assert len(calls) == 2
    assert calls[0][1] == calls[1][1] == {
        "X-Order-Validation-Deadline-Minutes": str(gateway.ORDER_VALIDATION_DEADLINE_MINUTES)
    }
