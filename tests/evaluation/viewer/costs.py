"""Reconstruct auditable costs from saved campaign diagnostics."""

from decimal import Decimal, InvalidOperation


RATE_VERSION = "evaluation-cost-rates-v1"
MILLION = Decimal("1000000")


def _decimal(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Rates must be finite non-negative decimals") from None
    if not number.is_finite() or number < 0:
        raise ValueError("Rates must be finite non-negative decimals")
    return number


def validate_rates(value):
    if not isinstance(value, dict) or value.get("schema_version") != RATE_VERSION or value.get("currency") != "USD":
        raise ValueError("Expected evaluation-cost-rates-v1 in USD")
    if set(value) - {"schema_version", "currency", "llm", "search"}:
        raise ValueError("Unknown cost rate fields")
    for category, fields, identity_fields in (
        ("llm", {"provider", "model", "input_usd_per_million_tokens", "output_usd_per_million_tokens"}, ("provider", "model")),
        ("search", {"provider", "usd_per_call"}, ("provider", "search_type")),
    ):
        rows = value.get(category, [])
        if not isinstance(rows, list):
            raise ValueError(f"{category} rates must be a list")
        seen = set()
        for row in rows:
            keys = set(row) if isinstance(row, dict) else set()
            tier_keys = {"included_results", "usd_per_additional_result"}
            if not isinstance(row, dict) or (category == "llm" and keys != fields) or (
                category == "search" and keys not in (fields, fields | tier_keys,
                                                       fields | {"search_type"}, fields | tier_keys | {"search_type"})
            ):
                raise ValueError(f"Invalid {category} rate entry")
            key = tuple(row.get(field) for field in identity_fields)
            if (not isinstance(row.get("provider"), str) or not row["provider"].strip()
                    or category == "llm" and (not isinstance(row.get("model"), str) or not row["model"].strip())
                    or category == "search" and "search_type" in row
                    and (not isinstance(row["search_type"], str) or not row["search_type"].strip())
                    or key in seen):
                raise ValueError(f"Duplicate or empty {category} rate identity")
            seen.add(key)
            if category == "search" and tier_keys <= keys and (
                not isinstance(row["included_results"], int) or isinstance(row["included_results"], bool)
                or row["included_results"] < 0
            ):
                raise ValueError("included_results must be a non-negative integer")
            for field in keys - set(identity_fields) - {"included_results"}:
                _decimal(row[field])
    return value


def _amount(number):
    return format(number.quantize(Decimal("0.00000001")), "f")


def _rate(rates, category, provider, model=None, search_type=None):
    rows = [row for row in rates.get(category, []) if row["provider"] == provider
            and (category != "llm" or row["model"] == model)]
    if category == "search" and search_type:
        exact = next((row for row in rows if row.get("search_type") == search_type), None)
        if exact:
            return exact
    return next((row for row in rows if category != "search" or "search_type" not in row), None)


def _event(event_id, component, provider, *, model=None, cost=None, quantity=1,
           unit="call", rate=None, reason=None, usage=None, row=None,
           input_cost=None, output_cost=None, search_type=None):
    row = row or {}
    return {"event_id": event_id, "component": component, "provider": provider, "model": model,
            "search_type": search_type,
            "run_id": row.get("run_id"), "assertion_id": row.get("assertion_id"),
            "validator_id": row.get("validator_id"), "quantity": quantity, "unit": unit,
            "usage": usage, "rate": rate, "cost_usd": _amount(cost) if cost is not None else None,
            "input_cost_usd": _amount(input_cost) if input_cost is not None else None,
            "output_cost_usd": _amount(output_cost) if output_cost is not None else None,
            "basis": "CALCULATED" if cost is not None else "UNKNOWN", "reason": reason}


def _search_events(trace, component, prefix, rates, row):
    if not isinstance(trace, dict):
        return []
    requests = trace.get("requests")
    if requests is None:
        requests = trace.get("query_execution") or []
    events = []
    for index, request in enumerate(requests):
        if not isinstance(request, dict) or request.get("status") not in {"EXECUTED", "FAILED"}:
            continue
        if component == "evidence_search" and not request.get("provider_call_id"):
            continue
        provider = request.get("provider") or trace.get("provider") or trace.get("discovery_provider")
        search_type = request.get("search_mode") or request.get("search_type")
        rate = _rate(rates, "search", provider, search_type=search_type)
        billable = request["status"] == "EXECUTED" or (rate is not None and _decimal(rate["usd_per_call"]) == 0)
        tiered = rate is not None and "included_results" in rate
        returned_urls = request.get("returned_urls")
        result_count = len(returned_urls) if isinstance(returned_urls, list) else None
        measured = not tiered or result_count is not None
        cost = None
        if rate and billable and measured:
            cost = _decimal(rate["usd_per_call"])
            if tiered:
                cost += max(0, result_count - rate["included_results"]) * _decimal(rate["usd_per_additional_result"])
        events.append(_event(f"{prefix}:{component}:{request.get('provider_call_id') or index}",
                             component, provider, cost=cost, search_type=search_type,
                             rate={key: value for key, value in rate.items() if key != "provider"} if rate else None,
                             reason=None if cost is not None else "BILLING_UNKNOWN" if rate and not billable
                             else "RESULT_COUNT_MISSING" if rate and not measured else "RATE_MISSING", row=row,
                             quantity=result_count if tiered and result_count is not None else 1,
                             unit="results" if tiered and result_count is not None else "call"))
    return events


def _llm_usage_event(event_id, component, provider, model, usage, rates, row=None):
    usage = usage or {}
    rate = _rate(rates, "llm", provider, model)
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    valid_usage = all(isinstance(n, int) and not isinstance(n, bool) and n >= 0
                      for n in (prompt, completion))
    input_cost = _decimal(rate["input_usd_per_million_tokens"]) * prompt / MILLION if rate and valid_usage else None
    output_cost = _decimal(rate["output_usd_per_million_tokens"]) * completion / MILLION if rate and valid_usage else None
    cost = input_cost + output_cost if input_cost is not None else None
    return _event(event_id, component, provider, model=model, cost=cost,
                  quantity=prompt + completion if valid_usage else 1,
                  unit="tokens" if valid_usage else "call",
                  rate={key: rate[key] for key in ("input_usd_per_million_tokens",
                                                   "output_usd_per_million_tokens")} if rate else None,
                  reason=None if cost is not None else "USAGE_MISSING" if not valid_usage else "RATE_MISSING",
                  usage={"input_tokens": prompt, "output_tokens": completion} if valid_usage else None,
                  row=row, input_cost=input_cost, output_cost=output_cost)


def _llm_event(row, rates, prefix):
    stage = row["stages"].get("llm") or {}
    if stage.get("execution_status") in {"SKIPPED", "NOT_RECORDED"}:
        return None
    obs = stage.get("observations") or {}
    if stage.get("execution_status") == "FAILED" and obs.get("validation_seconds") is None and not obs.get("usage"):
        return None
    provider = obs.get("provider") or (row.get("validator") or {}).get("provider")
    model = obs.get("model") or (row.get("validator") or {}).get("model")
    return _llm_usage_event(f"{prefix}:validator_llm", "validator_llm", provider, model,
                            obs.get("usage"), rates, row)


def summarize_events(events):
    unique = {event["event_id"]: event for event in events}
    def totals(group_events):
        known = sum((Decimal(event["cost_usd"]) for event in group_events if event["cost_usd"] is not None), Decimal(0))
        unknown = sum(event["cost_usd"] is None for event in group_events)
        reasons = {}
        for event in group_events:
            if event["cost_usd"] is None:
                reason = event.get("reason") or "UNKNOWN"
                reasons[reason] = reasons.get(reason, 0) + 1
        usages = [event["usage"] for event in group_events if event.get("usage")]
        def part(field):
            return _amount(sum((Decimal(event[field]) for event in group_events
                                if event.get(field) is not None), Decimal(0)))
        return {"known_usd": _amount(known), "total_usd": None if unknown or not group_events else _amount(known),
                "events": len(group_events), "unknown_events": unknown,
                "priced_events": len(group_events) - unknown, "unknown_reasons": reasons,
                "llm_priced_events": sum(event["component"].endswith("_llm") and event["cost_usd"] is not None
                                         for event in group_events),
                "llm_events_with_usage": len(usages),
                "search_priced_events": sum(event["component"] in {"router_discovery", "evidence_search"}
                                            and event["cost_usd"] is not None for event in group_events),
                "input_tokens": sum(item["input_tokens"] for item in usages),
                "output_tokens": sum(item["output_tokens"] for item in usages),
                "llm_events_without_usage": sum(event["component"].endswith("_llm") and not event.get("usage")
                                                for event in group_events),
                "input_cost_usd": part("input_cost_usd"), "output_cost_usd": part("output_cost_usd"),
                "search_cost_usd": _amount(sum((Decimal(event["cost_usd"]) for event in group_events
                                             if event["component"] in {"router_discovery", "evidence_search"}
                                             and event["cost_usd"] is not None), Decimal(0)))}
    values = list(unique.values())
    components = {}
    for event in values:
        components.setdefault(event["component"], []).append(event)
    return {**totals(values), "components": {name: totals(group) for name, group in components.items()}}


def order_costs(diagnostic, rates):
    identity = diagnostic["identity"]
    prefix = f"{identity['campaign_id']}:{identity['order_id']}:{identity['repetition']}"
    events = []
    generation = diagnostic["order"]["generation"]
    if generation.get("execution_status") in {"COMPLETED", "FAILED"}:
        obs = generation.get("observations") or {}
        if obs.get("provider") and obs.get("model") and obs.get("structured_attempts") != 0:
            usages = obs.get("usage") or [{}]
            for index, usage in enumerate(usages):
                events.append(_llm_usage_event(f"{prefix}:generation:{index}", "generation_llm",
                                               obs["provider"], obs["model"], usage, rates))
    validations = []
    validator_events = {}
    validator_validations = {}
    for row in diagnostic["validations"]:
        row_prefix = f"{prefix}:{row['run_id']}"
        row_events = []
        llm = _llm_event(row, rates, row_prefix)
        if llm:
            row_events.append(llm)
        for stage_name, component in (("router", "router_discovery"),
                                      ("evidence_search", "evidence_search")):
            stage = row["stages"].get(stage_name) or {}
            obs = stage.get("observations") or {}
            trace = obs.get("evaluation_trace") or {}
            if component == "evidence_search":
                trace = obs.get("provider_trace") or trace
            if (stage.get("execution_status") == "COMPLETED" and not trace
                    and (component == "evidence_search" and obs.get("cached") is False
                         and not obs.get("search_skipped")
                         or component == "router_discovery" and obs.get("route_state") in {"MISSING", "STALE"}
                         and not obs.get("stale_route_used"))):
                row_events.append(_event(f"{row_prefix}:{component}:unobserved", component,
                                         None, reason="TRACE_MISSING", row=row))
            row_events.extend(_search_events(trace, component, row_prefix, rates, row))
            if component == "router_discovery" and not trace.get("cache_hit") and (
                trace.get("classification_usage") or trace.get("classification") or
                trace.get("classification_error_type")
            ):
                for index, usage in enumerate(trace.get("classification_usage") or [{}]):
                    row_events.append(_llm_usage_event(f"{row_prefix}:router_classification:{index}",
                                                       "router_classification_llm",
                                                       trace.get("classification_provider"),
                                                       trace.get("classification_model"), usage, rates, row))
        events.extend(row_events)
        validator_key = row.get("validator_id") or "UNKNOWN"
        validator_events.setdefault(validator_key, []).extend(row_events)
        metadata = row.get("validator") or {}
        llm_observations = (row["stages"].get("llm") or {}).get("observations") or {}
        validations.append({"run_id": row["run_id"], "assertion_id": row["assertion_id"],
                            "validator_id": row["validator_id"],
                            "provider": llm_observations.get("provider") or metadata.get("provider"),
                            "model": llm_observations.get("model") or metadata.get("model"),
                            **summarize_events(row_events)})
        validator_validations.setdefault(validator_key, []).append(validations[-1])
    return {"order_id": identity["order_id"], "repetition": identity["repetition"],
            **summarize_events(events), "validations": validations, "ledger": events,
            "generation": summarize_events([event for event in events if event["component"] == "generation_llm"]),
            "validators": [{"validator_id": key, "validations": validator_validations[key],
                            **summarize_events(group)} for key, group in validator_events.items()]}
