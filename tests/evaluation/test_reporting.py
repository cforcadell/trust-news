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
