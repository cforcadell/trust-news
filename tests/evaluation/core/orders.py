"""Adapt existing LIGHT/BLOCKCHAIN order artifacts without inventing observations."""

from copy import deepcopy

from .artifacts import canonical_json, sha256_text
from .common_metrics import collect_assertions, match_assertions, validation_records, result_for_assertion, normalize_verdict
from .models import CaseResult


def results_from_order(dataset, order, run_id=None):
    generated = collect_assertions(order)
    matched = match_assertions(dataset, generated)
    matches = {m["expected_id"]: m for m in matched}
    results = []

    def append_results(expected, actual, aid, match, *, scoring_eligible):
        evaluated = bool(expected.get("required_terms")) and scoring_eligible
        records = validation_records(order, aid) if aid else []
        for validator_id, validation in records or [(None, {})]:
            raw_config = validation.get("validator_config") or {}
            config = raw_config.get("config", raw_config)
            public_config = {k: config[k] for k in ("provider", "model", "temperature", "config_version", "evidence_search_strategy") if k in config}
            public_config["id"] = validator_id
            public_config["validator_type"] = validation.get("validator_type")
            normalized_expected = {**deepcopy(expected), "expected_verdict": normalize_verdict(expected["expected_verdict"])}
            row = CaseResult(expected["id"], "FULL_PIPELINE", actual, normalized_expected,
                             dataset_id=dataset["id"], dataset_hash=sha256_text(canonical_json(dataset)),
                             order_id=order.get("order_id"), assertion_id=aid, validator=public_config)
            if (validation.get("evidence_search_response") or {}).get("validator_input", {}).get("context"):
                import json
                try:
                    row.assertion = json.loads(validation["evidence_search_response"]["validator_input"]["context"])["assertion"]
                except (ValueError, KeyError, TypeError):
                    pass
            row.provenance = {"parent_run_id": run_id, "correlation_id": validation.get("correlation_id"),
                              "origin": "persisted_order", "scoring_eligible": scoring_eligible}
            row.extraction = {"status": "UNMATCHED_GENERATED_ASSERTION" if not scoring_eligible else
                              "NOT_EVALUATED" if not evaluated else
                              "EXTRACTION_PASS" if match and match.get("category_match") is not False else "EXTRACTION_ERROR",
                              "method": "required_terms_and_category", "match": match}
            response = deepcopy(validation.get("evidence_search_response") or {})
            if response:
                route = response.pop("route", None)
                row.router = {"status": "COMPLETED", **route} if route else {"status": "NOT_EVALUATED"}
                row.retrieval = {"status": "COMPLETED", **response}
                inputs = response.get("validator_input", {})
                row.validator_input = {**inputs, "evidences": response.get("evidences", []),
                    "retrieval_evidence_bundle_hash": response.get("evidence_bundle_hash"),
                    "validator_input_evidence_bundle_hash": response.get("validator_input_evidence_bundle_hash")}
                row.cache_state.update(router_cache_hit=(route.get("route_state") == "FRESH" or bool(route.get("stale_route_used"))) if route else None,
                    evidence_cache_hit=response.get("cached"),
                    route_recomputed=(route.get("route_state") in {"MISSING", "STALE"}
                                      and not route.get("stale_route_used", False)) if route else None,
                    evidence_recomputed=response.get("cached") is False and not response.get("search_skipped"))
            audit = validation.get("evidence_validation") or {}
            row.grounding = {"validation": audit} if audit else {}
            if validation.get("execution_status") == "COMPLETED":
                row.validator_output = {"resultado": audit.get("original_verdict"),
                    "effective_verdict": normalize_verdict(validation.get("approval")),
                    "evidence_used": validation.get("evidence_used", []),
                    "evaluation_citation_trace": validation.get("evaluation_citation_trace")}
            if validation.get("execution_status") == "ERROR":
                details = validation.get("error_details") or {}
                error = {"stage": details.get("stage", "UNKNOWN"),
                         "code": "INVALID_RESPONSE" if details.get("stage") == "LLM_RESPONSE_PARSE" else "TECHNICAL_ERROR"}
                for key in ("exception_type", "status_code", "reason", "message"):
                    if details.get(key) not in (None, ""):
                        error[key] = details[key]
                row.errors = [error]
            if not records and match:
                row.errors = [{"stage": "VALIDATION", "code": "TECHNICAL_ERROR", "reason": "No validator responses"}]
            row.timings = {"validation_seconds": validation.get("response_time_seconds")}
            aggregate = result_for_assertion(order, aid) if aid else None
            if aggregate:
                row.consensus = {"status": "COMPLETED", **aggregate}
            results.append(row)

    for expected in dataset["assertions"]:
        match = matches.get(expected["id"])
        actual = deepcopy(generated[match["generated_index"]]) if match else {"text": expected.get("text", "")}
        aid = match["generated_id"] if match else None
        append_results(expected, actual, aid, match, scoring_eligible=True)

    matched_indexes = {match["generated_index"] for match in matched}
    for index, assertion in enumerate(generated):
        if index in matched_indexes:
            continue
        aid = str(assertion.get("idAssertion") or assertion.get("assertion_id") or assertion.get("id") or index + 1)
        expected = {"id": f"UNMATCHED::{aid}", "text": str(assertion.get("text") or assertion.get("assertion") or ""),
                    "expected_verdict": "UNKNOWN", "evaluation_scope": "OBSERVATION_ONLY"}
        append_results(expected, deepcopy(assertion), aid, None, scoring_eligible=False)
    from evaluation.pipeline.metrics import evaluate
    from evaluation.pipeline.root_cause import diagnose
    for row in results:
        row.metrics = evaluate(row)
        row.root_cause = diagnose(row.to_dict())
    return results
