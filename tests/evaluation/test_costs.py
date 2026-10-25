"""Prices are frozen per campaign and summaries reconcile with physical calls."""

import json
from pathlib import Path

import pytest

from evaluation.viewer.costs import order_costs, summarize_events, validate_rates
from evaluation.viewer.server import index_campaign


FIXTURE = Path(__file__).resolve().parents[1] / "data/evaluation/resources/viewer-fixtures/order-diagnostic-v1.json"
RATES = {"schema_version": "evaluation-cost-rates-v1", "currency": "USD",
         "llm": [{"provider": "openrouter", "model": "model-a",
                  "input_usd_per_million_tokens": "1", "output_usd_per_million_tokens": "2"}],
         "search": [{"provider": "exa", "usd_per_call": "0.01"}]}


def _diagnostic():
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    row = document["validations"][0]
    row["stages"]["llm"]["execution_status"] = "COMPLETED"
    row["stages"]["llm"]["observations"].update(
        provider="openrouter", model="model-a",
        usage={"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500})
    row["stages"]["evidence_search"]["observations"]["provider_trace"] = {
        "provider": "exa", "requests": [
            {"provider_call_id": "exa-1", "status": "EXECUTED"},
            {"status": "SKIPPED"},
            {"provider_call_id": "exa-2", "status": "FAILED"},
        ]}
    return document


def test_costs_include_real_calls_and_leave_failed_billing_unknown():
    costs = order_costs(_diagnostic(), validate_rates(RATES))
    first = costs["validations"][0]
    assert first["known_usd"] == "0.01200000"
    assert first["input_tokens"] == 1000
    assert first["output_tokens"] == 500
    assert first["input_cost_usd"] == "0.00100000"
    assert first["output_cost_usd"] == "0.00100000"
    assert first["search_cost_usd"] == "0.01000000"
    assert costs["components"]["evidence_search"]["known_usd"] == "0.01000000"
    assert costs["components"]["evidence_search"]["priced_events"] == 1
    assert costs["validators"][0]["known_usd"] == first["known_usd"]
    assert first["unknown_events"] == 1
    assert costs["total_usd"] is None
    assert costs["known_usd"] == summarize_events(costs["ledger"])["known_usd"]
    assert costs["priced_events"] == 2
    assert costs["unknown_reasons"]["BILLING_UNKNOWN"] == 1
    assert summarize_events(costs["ledger"] + costs["ledger"])["known_usd"] == costs["known_usd"]
    assert any(event["reason"] == "BILLING_UNKNOWN" for event in costs["ledger"])
    assert not any(event["event_id"].endswith("SKIPPED") for event in costs["ledger"])


def test_missing_price_and_missing_tokens_remain_unknown():
    diagnostic = _diagnostic()
    diagnostic["validations"][0]["stages"]["llm"]["observations"].pop("usage")
    costs = order_costs(diagnostic, validate_rates({"schema_version": "evaluation-cost-rates-v1",
                                                    "currency": "USD", "llm": [], "search": []}))
    assert costs["total_usd"] is None
    assert any(event["reason"] == "USAGE_MISSING" for event in costs["ledger"])
    assert any(event["reason"] == "RATE_MISSING" for event in costs["ledger"])
    with pytest.raises(ValueError):
        validate_rates({**RATES, "search": [{"provider": "exa", "usd_per_call": "NaN"}]})


def test_tiered_search_rate_uses_returned_result_count():
    diagnostic = _diagnostic()
    requests = diagnostic["validations"][0]["stages"]["evidence_search"]["observations"]["provider_trace"]["requests"]
    requests[0]["returned_urls"] = [f"https://example.org/{i}" for i in range(13)]
    requests[2]["returned_urls"] = []
    rates = validate_rates({**RATES, "search": [{"provider": "exa", "usd_per_call": "0.007",
        "included_results": 10, "usd_per_additional_result": "0.001"}]})
    events = [event for event in order_costs(diagnostic, rates)["ledger"] if event["component"] == "evidence_search"]
    assert events[0]["cost_usd"] == "0.01000000"
    assert events[0]["quantity"] == 13
    assert events[1]["reason"] == "BILLING_UNKNOWN"
    requests[0].pop("returned_urls")
    events = [event for event in order_costs(diagnostic, rates)["ledger"] if event["component"] == "evidence_search"]
    assert events[0]["reason"] == "RESULT_COUNT_MISSING"
    with pytest.raises(ValueError):
        validate_rates({**RATES, "search": [{"provider": "exa", "usd_per_call": "0.007",
            "usd_per_additional_result": "0.001"}]})


def test_search_tiers_are_priced_separately_without_changing_legacy_events():
    diagnostic = _diagnostic()
    requests = diagnostic["validations"][0]["stages"]["evidence_search"]["observations"]["provider_trace"]["requests"]
    requests[0].update(search_profile="primary", search_mode="lite", returned_urls=["https://example.org/1"])
    requests[2].update(search_type="auto", status="EXECUTED", returned_urls=["https://example.org/2"])
    rates = validate_rates({**RATES, "search": [
        {"provider": "exa", "usd_per_call": "0.007"},
        {"provider": "exa", "search_type": "lite", "usd_per_call": "0.004"},
    ]})
    events = [e for e in order_costs(diagnostic, rates)["ledger"] if e["component"] == "evidence_search"]
    assert [(e["search_type"], e["cost_usd"]) for e in events] == [
        ("lite", "0.00400000"), ("auto", "0.00700000")]


def test_generation_repair_and_router_classification_use_each_recorded_response():
    diagnostic = _diagnostic()
    generation = diagnostic["order"]["generation"]["observations"]
    generation.update(provider="openrouter", model="model-a", usage=[
        {"prompt_tokens": 100, "completion_tokens": 50},
        {"prompt_tokens": 50, "completion_tokens": 20},
    ])
    router = diagnostic["validations"][0]["stages"]["router"]["observations"]
    router["evaluation_trace"] = {
        "cache_hit": False, "classification_provider": "openrouter",
        "classification_model": "model-a", "classification_usage": [
            {"prompt_tokens": 40, "completion_tokens": 10}],
    }
    costs = order_costs(diagnostic, validate_rates(RATES))
    generation_events = [event for event in costs["ledger"] if event["component"] == "generation_llm"]
    router_events = [event for event in costs["ledger"] if event["component"] == "router_classification_llm"]
    assert len(generation_events) == 2
    assert [event["cost_usd"] for event in generation_events] == ["0.00020000", "0.00009000"]
    assert [event["cost_usd"] for event in router_events] == ["0.00006000"]
    assert costs["input_tokens"] >= 1190
    assert costs["output_tokens"] >= 580
    assert costs["generation"]["input_tokens"] == 150
    assert costs["components"]["router_classification_llm"]["output_tokens"] == 10


def test_uncaptured_live_search_does_not_make_total_look_complete():
    diagnostic = _diagnostic()
    diagnostic["validations"][0]["stages"]["evidence_search"]["observations"].pop("provider_trace")
    diagnostic["validations"][0]["stages"]["evidence_search"]["observations"]["cached"] = False
    costs = order_costs(diagnostic, validate_rates(RATES))
    assert any(event["reason"] == "TRACE_MISSING" for event in costs["ledger"])
    assert costs["total_usd"] is None


def test_campaign_costs_match_order_and_keep_rate_snapshot(tmp_path):
    directory = tmp_path / "fixture-campaign"
    directory.mkdir()
    (directory / "fixture-parent-viewer.json").write_text(json.dumps(_diagnostic()), encoding="utf-8")
    (directory / "cost-rates.json").write_text(json.dumps(RATES), encoding="utf-8")
    indexed = index_campaign(tmp_path, "fixture-campaign")
    assert indexed["costs"]["known_usd"] == indexed["orders"][0]["costs"]["known_usd"]
    assert indexed["costs"]["input_tokens"] == indexed["orders"][0]["costs"]["input_tokens"]
    assert indexed["costs"]["search_cost_usd"] == indexed["orders"][0]["costs"]["search_cost_usd"]
    assert indexed["costs"]["rates_configured"] is True
    assert indexed["costs"]["total_usd"] is None


def test_order_totals_reconcile_generation_validators_and_search():
    diagnostic = _diagnostic()
    diagnostic["order"]["generation"]["observations"].update(
        provider="openrouter", model="model-a", structured_attempts=1,
        usage=[{"prompt_tokens": 200, "completion_tokens": 100}])
    diagnostic["validations"][0]["stages"]["evidence_search"]["observations"]["provider_trace"]["requests"] = [
        {"provider_call_id": "exa-1", "status": "EXECUTED"}]
    second = json.loads(json.dumps(diagnostic["validations"][0]))
    second["run_id"] = "other-run"
    second["validator_id"] = "other-validator"
    second["stages"]["evidence_search"]["observations"].pop("provider_trace")
    second["stages"]["evidence_search"]["execution_status"] = "SKIPPED"
    diagnostic["validations"].append(second)
    costs = order_costs(diagnostic, validate_rates(RATES))
    assert len(costs["validators"]) == 2
    assert costs["input_tokens"] == costs["generation"]["input_tokens"] + sum(
        group["input_tokens"] for group in costs["validators"])
    assert costs["output_tokens"] == costs["generation"]["output_tokens"] + sum(
        group["output_tokens"] for group in costs["validators"])
    assert costs["known_usd"] == "0.01440000"
    assert costs["search_cost_usd"] == "0.01000000"
    assert costs["components"]["evidence_search"]["known_usd"] == costs["search_cost_usd"]
