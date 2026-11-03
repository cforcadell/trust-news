import json

import pytest

from evaluation.core.cli import main
from evaluation.core.orders import results_from_order
from evaluation.core.consensus import attach_consensus
from evaluation.core.reporting import llm_report, pipeline_report
from evaluation.pipeline.metrics import evaluate
from evaluation.pipeline.root_cause import diagnose
from evaluation.test_execution import case, run, answer


def evaluated(row):
    row["metrics"] = evaluate(row)
    row["root_cause"] = diagnose(row)
    return row


def test_cli_gold_and_replay_share_artifacts(tmp_path, monkeypatch):
    import common.llm
    monkeypatch.setattr(common.llm, "complete", answer)
    dataset = tmp_path / "case.json"
    dataset.write_text(json.dumps(case()))
    output = tmp_path / "gold"
    assert main("llm", ["--dataset", str(dataset), "--model", "openrouter:test", "--output", str(output)]) == 0
    report = json.loads((output / "report.json").read_text())
    assert report["models"][0]["accuracy"] == 1
    assert report["models"][0]["total_tokens"] == 10
    manifest = json.loads((output / "manifest.json").read_text())
    artifact = output / (manifest["runs"][0] + ".json")
    assert main("llm", ["--mode", "replay", "--replay-artifact", str(artifact), "--model", "mistral:test", "--output", str(tmp_path / "replay")]) == 0


def test_old_order_missing_handoff_not_passed():
    dataset = case()
    order = {"order_id": "order", "assertions": [{"idAssertion": "1", "text": dataset["assertions"][0]["text"]}],
             "validations": {"1": {"v": {"execution_status": "COMPLETED", "approval": "TRUE",
                 "evidence_search_response": {"evidences": [], "cached": True}}}}}
    result = results_from_order(dataset, order)[0]
    assert result.order_id == "order"
    assert result.extraction["status"] == "EXTRACTION_PASS"
    assert evaluate(result)["handoff"]["status"] == "NOT_EVALUATED"


def test_imported_order_preserves_validator_usage_for_costs():
    dataset = case()
    order = {"order_id": "order", "assertions": [{"idAssertion": "1", "text": dataset["assertions"][0]["text"]}],
             "validations": {"1": {"v": {"execution_status": "COMPLETED", "approval": "TRUE",
                 "llm_usage": {"prompt_tokens": 120, "completion_tokens": 40},
                 "resolved_model": "model-a"}}}}
    result = results_from_order(dataset, order)[0]
    assert result.validator_output["usage"] == {"prompt_tokens": 120, "completion_tokens": 40}
    assert result.validator_output["resolved_model"] == "model-a"


def test_extraction_missing_and_unevaluable_are_distinct():
    dataset = case()
    result = results_from_order(dataset, {"assertions": []})[0].to_dict()
    assert evaluated(result)["root_cause"]["code"] == "EXTRACTION_ERROR"
    del dataset["assertions"][0]["required_terms"]
    result = results_from_order(dataset, {"assertions": []})[0].to_dict()
    assert evaluate(result)["extraction"]["status"] == "NOT_EVALUATED"


def test_models_modes_and_unevaluated_e2e_not_mixed():
    gold = evaluated(run().to_dict())
    replay = evaluated(run("VALIDATOR_REPLAY", replay=gold).to_dict())
    assert len(llm_report([gold, replay])["models"]) == 2
    summary = pipeline_report([gold, replay])
    assert summary["total_cases"] == 1
    assert summary["not_evaluated"] == 1
    assert summary["end_to_end_correct"] == 0


def test_pipeline_report_aggregates_download_observability():
    row = evaluated(run().to_dict())
    row["execution_mode"] = "FULL_PIPELINE"
    row["metrics"]["retrieval"].update({
        "response_present": True,
        "response_cached": False,
        "documents_attempted": 3,
        "documents_extracted": 2,
        "documents_citable": 1,
        "http_requests": 3,
        "http_responses": 3,
        "http_successes": 2,
        "retry_actions": 1,
        "retry_recovered": 1,
        "retry_exhausted": 0,
        "candidate_substitutions": 1,
        "substitution_recovered": 1,
        "substitution_exhausted": 0,
        "fetch_outcome_counts": {"EXTRACTED": 2, "ACCESS_DENIED": 1},
    })

    observed = pipeline_report([row])["retrieval_observability"]

    assert observed == {
        "responses": 1,
        "cached_responses": 0,
        "documents_attempted": 3,
        "documents_extracted": 2,
        "documents_citable": 1,
        "usable_download_percent": pytest.approx(66.6666666667),
        "citable_document_percent": pytest.approx(33.3333333333),
        "http_requests": 3,
        "http_responses": 3,
        "http_successes": 2,
        "http_success_percent": pytest.approx(66.6666666667),
        "retry_actions": 1,
        "retry_recovered": 1,
        "retry_exhausted": 0,
        "candidate_substitutions": 1,
        "substitution_recovered": 1,
        "substitution_exhausted": 0,
        "fetch_outcomes": {"EXTRACTED": 2, "ACCESS_DENIED": 1},
    }

    missing = evaluated(run().to_dict())
    missing["execution_mode"] = "FULL_PIPELINE"
    missing["metrics"]["retrieval"].update({
        "status": "NOT_EVALUATED",
        "response_present": False,
    })
    assert pipeline_report([row, missing])["retrieval_observability"]["responses"] == 1


def test_consensus_uses_production_abstention_policy():
    a, b = run().to_dict(), run().to_dict()
    for row in (a, b):
        row["execution_mode"] = "FULL_PIPELINE"
    b["validator"]["id"] = "second"
    b["validator_output"]["effective_verdict"] = "UNKNOWN"
    attach_consensus([a, b])
    assert a["consensus"]["verdict"] == "UNKNOWN"
    assert a["consensus"]["reason_code"] == "DECISIVE_COVERAGE_TOO_LOW"
    assert evaluated(a)["root_cause"]["code"] == "CONSENSUS_ERROR"


def test_handoff_has_priority_over_llm_attribution():
    row = run().to_dict()
    row["validator_input"]["retrieval_evidence_bundle_hash"] = "different"
    assert evaluated(row)["root_cause"]["code"] == "HANDOFF_EVIDENCE_MISMATCH"


def test_cold_frozen_conflict_rejected_before_llm():
    from evaluation.core.artifacts import EvaluationError
    with pytest.raises(EvaluationError):
        run(cache_mode="COLD")


def test_publish_uses_shared_light_runner_and_imports_results(tmp_path, monkeypatch):
    from unittest.mock import Mock
    import evaluation.core.cli as cli
    from evaluation.core.order_execution import publish_and_wait
    dataset = case()
    path = tmp_path / "case.json"
    path.write_text(json.dumps(dataset))
    client = Mock()
    client.post.return_value = {"order_id": "order-id"}
    order = {"order_id": "order-id", "assertions": [{"idAssertion": "1", "text": dataset["assertions"][0]["text"]}],
        "validations": {"1": {"validator": {"execution_status": "COMPLETED", "approval": "TRUE"}}}}
    wait = Mock(return_value=order)
    monkeypatch.setattr(cli, "legacy_client", lambda *args: (client, wait))
    output = tmp_path / "published"
    assert cli.main("pipeline", ["--dataset", str(path), "--publish", "--output", str(output)]) == 0
    client.post.assert_called_once_with("/orders/publishNew", {"text": dataset["news"], "validation_mode": "LIGHT"})
    report = json.loads((output / "report.json").read_text())
    assert report["end_to_end_correct"] == 1
    manifest = json.loads((output / "manifest.json").read_text())
    artifact = json.loads((output / (manifest["runs"][0] + ".json")).read_text())
    assert artifact["order_id"] == "order-id"
    assert artifact["provenance"]["parent_run_id"]


def test_publish_terminal_failure_preserves_order_for_viewer(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from evaluation.core.artifacts import BenchmarkError
    import evaluation.core.cli as cli
    dataset = case()
    path = tmp_path / "case.json"
    path.write_text(json.dumps(dataset))
    client = Mock()
    client.post.return_value = {"order_id": "failed-order"}
    failed_order = {"order_id": "failed-order", "status": "ASSERTIONS_NOT_AVAILABLE",
                    "text": dataset["news"], "assertions": [],
                    "assertions_error": {"provider": "example", "error": "unavailable"}}
    client.get.return_value = failed_order
    wait = Mock(side_effect=BenchmarkError(
        "La orden failed-order terminó en ASSERTIONS_NOT_AVAILABLE"))
    monkeypatch.setattr(cli, "legacy_client", lambda *args: (client, wait))
    output = tmp_path / "failed-published"

    assert cli.main("pipeline", ["--dataset", str(path), "--publish", "--output", str(output)]) == 1

    viewers = list(output.glob("*-viewer.json"))
    orders = list(output.glob("*-order.json"))
    assert len(viewers) == 1
    assert len(orders) == 1
    snapshot = json.loads(viewers[0].read_text())
    assert snapshot["identity"]["order_id"] == "failed-order"
    assert snapshot["order"]["status"] == "ASSERTIONS_NOT_AVAILABLE"
    assert snapshot["order"]["generation"]["assessment"] == "FAIL"
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["failures"][0]["diagnostic_code"] == "ORDER_TERMINAL_FAILURE"
    artifact = json.loads(next(path for path in output.glob("*.json") if path.stem in manifest["runs"]).read_text())
    assert artifact["errors"][0]["reason"] == "La orden failed-order terminó en ASSERTIONS_NOT_AVAILABLE"


def test_publish_authentication_failure_is_explicit_and_grouped(tmp_path, monkeypatch, capsys):
    from unittest.mock import Mock
    from evaluation.core.artifacts import BenchmarkError
    import evaluation.core.cli as cli
    dataset = case()
    second = json.loads(json.dumps(dataset["assertions"][0]))
    second["id"] = "case-2"
    second["text"] = "Segunda afirmación del mismo pedido."
    dataset["assertions"].append(second)
    path = tmp_path / "case.json"
    path.write_text(json.dumps(dataset))
    client = Mock()
    client.post.side_effect = BenchmarkError(
        "No se pudo obtener token de Keycloak: <urlopen error [Errno 111] Connection refused>")
    monkeypatch.setattr(cli, "legacy_client", lambda *args: (client, Mock()))
    output = tmp_path / "auth-failure"

    assert cli.main("pipeline", ["--dataset", str(path), "--publish", "--output", str(output)]) == 1

    traces = capsys.readouterr().out
    assert "phase=repetition.failed" in traces
    assert "stage=AUTHENTICATION" in traces
    assert "diagnostic_code=AUTHENTICATION_ERROR" in traces
    assert "Connection refused" in traces
    assert "phase=order.snapshot.skipped" in traces
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["failures"][0]["order_id"] is None
    assert manifest["failures"][0]["diagnostic_code"] == "AUTHENTICATION_ERROR"
    report = json.loads((output / "report.json").read_text())
    assert len(report["execution_failures"]) == 1
    assert report["execution_failures"][0]["affected_cases"] == [
        dataset["assertions"][0]["id"], "case-2"]


def test_publish_timeout_records_limit_and_last_status(tmp_path, monkeypatch, capsys):
    from unittest.mock import Mock
    from evaluation.core.artifacts import BenchmarkError
    import evaluation.core.cli as cli
    dataset = case()
    path = tmp_path / "case.json"
    path.write_text(json.dumps(dataset))
    client = Mock()
    client.post.return_value = {"order_id": "slow-order"}
    client.get.return_value = {"order_id": "slow-order", "status": "PROCESSING", "assertions": []}
    wait = Mock(side_effect=BenchmarkError(
        "Timeout esperando la orden slow-order; último estado: PROCESSING"))
    monkeypatch.setattr(cli, "legacy_client", lambda *args: (client, wait))
    output = tmp_path / "timeout"

    assert cli.main("pipeline", ["--dataset", str(path), "--publish", "--result-timeout", "120",
                                 "--output", str(output)]) == 1

    traces = capsys.readouterr().out
    assert "diagnostic_code=ORDER_TIMEOUT" in traces
    assert "último estado: PROCESSING" in traces
    manifest = json.loads((output / "manifest.json").read_text())
    failure = manifest["failures"][0]
    assert failure["stage"] == "ORDER_POLL"
    assert failure["timeout_seconds"] == 120.0
    assert failure["order_id"] == "slow-order"
    assert list(output.glob("*-order.json"))


def test_error_diagnostics_redact_credentials():
    from evaluation.core.artifacts import safe_error_text

    value = safe_error_text("connection failed password=hunter2 Authorization: Bearer abc.def.ghi")
    assert "hunter2" not in value
    assert "Bearer abc" not in value
    assert "[REDACTED]" in value


def test_existing_output_is_rejected_before_any_llm_call(tmp_path, monkeypatch):
    from unittest.mock import Mock
    import common.llm
    model = Mock()
    monkeypatch.setattr(common.llm, "complete", model)
    dataset = tmp_path / "case.json"
    dataset.write_text(json.dumps(case()))
    with pytest.raises(SystemExit):
        main("llm", ["--dataset", str(dataset), "--model", "openrouter:test", "--output", str(tmp_path)])
    model.assert_not_called()


def test_retrieval_counterfactual_and_incomparable_configuration():
    from unittest.mock import Mock
    from evaluation.core.evidence import gold_bundle
    from common.utils.evidence_bundle import evidence_bundle_hash
    services = Mock()
    services.route.return_value = {"sources": [{"domain": "example.org"}], "route_state": "FRESH"}
    services.retrieve.return_value = {"evidences": [], "cached": False, "evidence_bundle_hash": evidence_bundle_hash([])}
    full = evaluated(run("FULL_PIPELINE", services=services).to_dict())
    domains = evaluated(run("GOLD_DOMAINS", services=services).to_dict())
    gold = evaluated(run().to_dict())
    assert diagnose(full, [domains, gold])["code"] == "RETRIEVAL_NO_RESULT"
    # A passing GOLD_DOMAINS execution on another model cannot establish router causality.
    different = evaluated(run().to_dict())
    different["execution_mode"] = "GOLD_DOMAINS"
    different["validator"]["model"] = "different-model"
    assert diagnose(full, [different])["code"] != "ROUTER_WRONG_SOURCE"


def test_order_export_has_metrics_root_cause_and_stale_cache_observation():
    dataset = case()
    dataset["assertions"][0]["expected_verdict"] = 1
    order = {"assertions": [{"idAssertion": "1", "text": dataset["assertions"][0]["text"]}],
        "validations": {"1": {"v": {"execution_status": "COMPLETED", "approval": 1,
            "evidence_search_response": {"route": {"route_state": "STALE", "stale_route_used": True,
                "sources": [{"domain": "example.org"}]}, "evidences": [], "cached": True}}}},
        "assertion_results": {"1": {"verdict": "UNKNOWN"}}}
    row = results_from_order(dataset, order)[0].to_dict()
    assert row["metrics"]["validation"]["correct"] is True
    assert row["root_cause"]["code"] == "CONSENSUS_ERROR"
    assert row["cache_state"]["router_cache_hit"] is True
    assert row["cache_state"]["route_recomputed"] is False
    assert pipeline_report([row])["end_to_end_incorrect"] == 1


def test_handoff_failure_is_not_an_end_to_end_success():
    row = run().to_dict()
    row["execution_mode"] = "FULL_PIPELINE"
    row["validator_input"]["retrieval_evidence_bundle_hash"] = "different"
    evaluated(row)
    report = pipeline_report([row])
    assert report["end_to_end_correct"] == 0
    assert report["end_to_end_incorrect"] == 1


def test_taxonomy_mismatch_is_separate_from_decision_correctness():
    dataset = case()
    dataset["assertions"][0]["category_ids"] = [9]
    order = {
        "order_id": "taxonomy-order",
        "assertions": [{"idAssertion": "1", "text": dataset["assertions"][0]["text"], "categoryId": 1}],
        "validations": {"1": {"validator": {"execution_status": "COMPLETED", "approval": "TRUE"}}},
        "assertion_results": {"1": {"status": "COMPLETED", "verdict": "TRUE"}},
    }

    row = results_from_order(dataset, order)[0].to_dict()
    report = pipeline_report([row])

    assert row["extraction"]["status"] == "TAXONOMY_MISMATCH"
    assert row["extraction"]["assertion_match"] == "PASS"
    assert row["extraction"]["taxonomy"] == "FAIL"
    assert row["root_cause"]["code"] == "TAXONOMY_MISMATCH"
    assert report["decision_correct"] == 1
    assert report["strict_pipeline_fail"] == 1
    assert report["taxonomy_mismatches"] == 1
    assert report["failures"]["taxonomy"] == 1


def test_validator_error_with_valid_consensus_is_quorum_degraded():
    row = run().to_dict()
    row["execution_mode"] = "FULL_PIPELINE"
    row["errors"] = [{"stage": "SOURCE_ROUTER", "code": "TECHNICAL_ERROR"}]
    row["consensus"] = {"status": "COMPLETED", "verdict": "TRUE"}
    evaluated(row)

    report = pipeline_report([row])

    assert report["decision_correct"] == 1
    assert report["strict_pipeline_fail"] == 1
    assert report["quorum_degraded"] == 1
    assert report["operational"] == {"pass": 0, "degraded": 1, "fail": 0}


def test_unmatched_generated_validation_is_visible_but_not_scored():
    dataset = case()
    order = {"assertions": [{"idAssertion": "extra", "text": "Texto ajeno al caso gold."}],
             "validations": {"extra": {"validator": {"execution_status": "ERROR",
                 "error_details": {"stage": "LLM_REQUEST", "status_code": 429,
                                   "message": "rate limited"}}}}}
    rows = [row.to_dict() for row in results_from_order(dataset, order)]
    observed = next(row for row in rows if row["provenance"].get("scoring_eligible") is False)
    assert observed["extraction"]["status"] == "UNMATCHED_GENERATED_ASSERTION"
    assert observed["metrics"]["validation"]["correct"] is None
    assert observed["errors"][0]["status_code"] == 429
    report = pipeline_report(rows)
    assert report["total_cases"] == 1
    assert report["observation_only_executions"] == 1
    assert report["failures"]["technical"] == 1


def test_annotated_numeric_evidence_contradiction_has_specific_cause():
    row = run().to_dict()
    row["expected"]["approximate_values"] = [{"value": 24.5, "tolerance": 0.5,
                                                "aliases": ["una cuarta parte"]}]
    row["assertion"]["text"] = "La cuota fue aproximadamente una cuarta parte."
    row["validator_input"]["evidences"] = [{"contexts": [
        {"text": "The measured share was 24.5%.", "citation_eligible": True}]}]
    row["validator_output"]["effective_verdict"] = "FALSE"
    evaluated(row)
    assert row["metrics"]["evidence_coherence"]["status"] == "VERDICT_EVIDENCE_CONTRADICTION"
    assert row["root_cause"]["code"] == "VERDICT_EVIDENCE_CONTRADICTION"


def test_cli_emits_secret_free_phase_traces(tmp_path, monkeypatch, capsys):
    import common.llm

    monkeypatch.setattr(common.llm, "complete", answer)
    dataset = tmp_path / "case.json"
    dataset.write_text(json.dumps(case()))
    output = tmp_path / "trace-run"

    assert main("llm", ["--dataset", str(dataset), "--model", "openrouter:test", "--output", str(output)]) == 0

    trace_lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("EVALUATION_TRACE ")]
    phases = {line.split(" phase=", 1)[1].split(" ", 1)[0] for line in trace_lines}
    assert {"campaign.prepared", "run.start", "router.skipped", "retrieval.injected",
            "validator_input.prepared", "validation.start", "validation.complete",
            "grounding.start", "grounding.complete", "run.persisted", "metrics.complete",
            "root_cause.complete", "campaign.complete"} <= phases
    assert all("api_key" not in line.lower() and "secret" not in line.lower() for line in trace_lines)
