"""Write immutable per-run artifacts; the two reports keep separate purposes."""

from collections import Counter
from pathlib import Path
import statistics

from .artifacts import write_json


def llm_report(rows):
    observation_only = [row for row in rows if row.get("provenance", {}).get("scoring_eligible") is False]
    rows = [row for row in rows if row.get("provenance", {}).get("scoring_eligible") is not False]
    groups = {}
    for row in rows:
        cfg = row["validator"]
        # Different modes/evidence scenarios must never silently share an average.
        key = (cfg.get("id"), cfg.get("provider"), cfg.get("model"), cfg.get("temperature"), row["execution_mode"])
        groups.setdefault(key, []).append(row)
    models = []
    for key, items in groups.items():
        evaluated = [r for r in items if r["metrics"]["validation"]["correct"] is not None]
        audits = [r["metrics"]["grounding"] for r in items if r["metrics"]["grounding"]["status"] != "NOT_EVALUATED"]
        latencies = [r["timings"].get("validation_seconds") for r in items]
        latencies = [n for n in latencies if isinstance(n, (int, float))]
        usage = [r["validator_output"].get("usage") for r in items]
        tokens = [u.get("total_tokens") for u in usage if u and u.get("total_tokens") is not None]
        claimed = sum(a.get("claimed_count") or 0 for a in audits)
        models.append({"validator": key[0], "provider": key[1], "model": key[2], "temperature": key[3], "execution_mode": key[4],
            "cases": len(items), "evaluated": len(evaluated),
            "accuracy": sum(r["metrics"]["validation"]["correct"] is True for r in items) / len(items),
            "verdict_distribution": dict(Counter(r["validator_output"].get("effective_verdict", "NO_RESPONSE") for r in items)),
            "grounding_success": sum(a["status"] == "GROUNDING_PASS" for a in audits) / len(audits) if audits else None,
            "citation_validity": sum(a.get("verified_count") or 0 for a in audits) / claimed if claimed else None,
            "abstention": sum(r["validator_output"].get("effective_verdict") == "UNKNOWN" for r in items) / len(items),
            "invalid_responses": sum(r["metrics"]["validation"]["status"] == "INVALID_RESPONSE" for r in items),
            "errors": sum(bool(r["errors"]) for r in items),
            "latency_mean_seconds": statistics.mean(latencies) if latencies else None,
            "total_tokens": sum(tokens) if tokens else None, "token_observations": len(tokens),
            "cost_usd": None,
            "evidence_bundle_hashes": sorted({r["validator_input"].get("validator_input_evidence_bundle_hash") for r in items} - {None})})
    comparisons = {}
    for row in rows:
        key = (row.get("dataset_id"), row["case_id"], row["execution_mode"])
        comparisons.setdefault(key, []).append(row)
    conditions = []
    for key, items in comparisons.items():
        hashes = [r["validator_input"].get("validator_input_evidence_bundle_hash") for r in items]
        prompts = [r["validator_input"].get("prompt_hash") for r in items]
        conditions.append({"dataset_id": key[0], "case_id": key[1], "execution_mode": key[2],
            "same_evidence": len(set(hashes)) == 1 if all(hashes) else None,
            "same_prompt": len(set(prompts)) == 1 if all(prompts) else None,
            "quality_scope": "validator_only" if key[2] in {"GOLD_EVIDENCE", "VALIDATOR_REPLAY"} else "pipeline_dependent"})
    return {"report": "llm-benchmark", "models": models, "comparison_conditions": conditions,
            "observation_only_executions": len(observation_only)}


def pipeline_report(rows):
    # Count assertions, not validators or counterfactual executions.
    all_rows = rows
    observation_only = [row for row in rows if row.get("provenance", {}).get("scoring_eligible") is False]
    rows = [row for row in rows if row.get("provenance", {}).get("scoring_eligible") is not False]
    groups = {}
    for row in rows:
        groups.setdefault((row.get("dataset_id"), row["case_id"], row.get("provenance", {}).get("repetition", 1)), []).append(row)
    strict_pass = strict_fail = strict_not_evaluated = 0
    decision_correct = decision_incorrect = decision_not_evaluated = 0
    taxonomy_mismatches = quorum_degraded = 0
    operational_pass = operational_degraded = operational_fail = 0
    causes = Counter()
    for items in groups.values():
        full = [r for r in items if r["execution_mode"] == "FULL_PIPELINE"]
        for code in {r["root_cause"]["code"] for r in (full or items)} - {None}:
            causes[code] += 1
        if not full:
            strict_not_evaluated += 1
            decision_not_evaluated += 1
            continue
        consensus = next((r["metrics"]["consensus"] for r in full if r["metrics"]["consensus"]["status"] != "NOT_EVALUATED"), None)
        observed = [r["metrics"]["validation"]["correct"] for r in full]
        if consensus:
            decision_passed = consensus["status"] == "CONSENSUS_PASS"
        elif len(full) == 1:
            decision_passed = observed[0]
        else:
            decision_passed = None  # Multiple validators without an observed consensus.
        if decision_passed is None:
            decision_not_evaluated += 1
        elif decision_passed:
            decision_correct += 1
        else:
            decision_incorrect += 1

        has_errors = any(r["errors"] for r in full)
        has_taxonomy_mismatch = any(
            r["metrics"]["extraction"]["status"] == "TAXONOMY_MISMATCH" for r in full)
        if has_taxonomy_mismatch:
            taxonomy_mismatches += 1
        if has_errors and consensus:
            quorum_degraded += 1
            operational_degraded += 1
        elif has_errors:
            operational_fail += 1
        else:
            operational_pass += 1

        strict_passed = decision_passed
        if any(r["errors"] or r["metrics"]["extraction"]["status"] in {"EXTRACTION_ERROR", "TAXONOMY_MISMATCH"}
               or r["metrics"]["handoff"]["status"] == "HANDOFF_EVIDENCE_MISMATCH" for r in full):
            strict_passed = False
        if strict_passed is None:
            strict_not_evaluated += 1
        elif strict_passed:
            strict_pass += 1
        else:
            strict_fail += 1
    observation_causes = Counter(row.get("root_cause", {}).get("code") for row in observation_only
                                 if row.get("root_cause", {}).get("code"))
    observed_causes = causes + observation_causes
    full_pipeline_rows = [row for row in rows if row["execution_mode"] == "FULL_PIPELINE"]
    retrieval_metrics = [row.get("metrics", {}).get("retrieval", {}) for row in full_pipeline_rows]
    documents_attempted = sum(metric.get("documents_attempted") or 0 for metric in retrieval_metrics)
    documents_extracted = sum(metric.get("documents_extracted") or 0 for metric in retrieval_metrics)
    documents_citable = sum(metric.get("documents_citable") or 0 for metric in retrieval_metrics)
    http_requests = sum(metric.get("http_requests") or 0 for metric in retrieval_metrics)
    http_responses = sum(metric.get("http_responses") or 0 for metric in retrieval_metrics)
    http_successes = sum(metric.get("http_successes") or 0 for metric in retrieval_metrics)
    retry_actions = sum(metric.get("retry_actions") or 0 for metric in retrieval_metrics)
    candidate_substitutions = sum(
        metric.get("candidate_substitutions") or 0 for metric in retrieval_metrics
    )
    fetch_outcomes = Counter()
    for metric in retrieval_metrics:
        fetch_outcomes.update(metric.get("fetch_outcome_counts") or {})
    retrieval_observability = {
        "responses": sum(metric.get("response_present", metric.get("status") != "NOT_EVALUATED")
                         for metric in retrieval_metrics),
        "cached_responses": sum(metric.get("response_cached") is True for metric in retrieval_metrics),
        "documents_attempted": documents_attempted,
        "documents_extracted": documents_extracted,
        "documents_citable": documents_citable,
        "usable_download_percent": (
            documents_extracted / documents_attempted * 100 if documents_attempted else None
        ),
        "citable_document_percent": (
            documents_citable / documents_attempted * 100 if documents_attempted else None
        ),
        "http_requests": http_requests,
        "http_responses": http_responses,
        "http_successes": http_successes,
        "http_success_percent": http_successes / http_requests * 100 if http_requests else None,
        "retry_actions": retry_actions,
        "retry_recovered": sum(metric.get("retry_recovered") or 0 for metric in retrieval_metrics),
        "retry_exhausted": sum(metric.get("retry_exhausted") or 0 for metric in retrieval_metrics),
        "candidate_substitutions": candidate_substitutions,
        "substitution_recovered": sum(metric.get("substitution_recovered") or 0 for metric in retrieval_metrics),
        "substitution_exhausted": sum(metric.get("substitution_exhausted") or 0 for metric in retrieval_metrics),
        "fetch_outcomes": dict(fetch_outcomes),
    }
    grouped_failures = {}
    for row in all_rows:
        parent_run_id = row.get("provenance", {}).get("parent_run_id")
        for error in row.get("errors") or []:
            key = (parent_run_id, row.get("order_id"), error.get("stage"), error.get("diagnostic_code"),
                   error.get("exception_type"), error.get("reason"), error.get("status_code"))
            item = grouped_failures.setdefault(key, {
                "parent_run_id": parent_run_id, "order_id": row.get("order_id"),
                **{name: error.get(name) for name in
                   ("stage", "code", "diagnostic_code", "exception_type", "reason", "status_code", "timeout_seconds")
                   if error.get(name) is not None},
                "affected_cases": [],
            })
            if row.get("case_id") not in item["affected_cases"]:
                item["affected_cases"].append(row.get("case_id"))
    return {"report": "pipeline-evaluation", "total_cases": len(groups), "executions": len(all_rows),
            "scored_executions": len(rows), "observation_only_executions": len(observation_only),
            # Backward-compatible aliases retain the historical strict gate.
            "end_to_end_correct": strict_pass, "end_to_end_incorrect": strict_fail,
            "not_evaluated": strict_not_evaluated,
            "decision_correct": decision_correct, "decision_incorrect": decision_incorrect,
            "decision_not_evaluated": decision_not_evaluated,
            "strict_pipeline_pass": strict_pass, "strict_pipeline_fail": strict_fail,
            "strict_pipeline_not_evaluated": strict_not_evaluated,
            "taxonomy_mismatches": taxonomy_mismatches, "quorum_degraded": quorum_degraded,
            "operational": {"pass": operational_pass, "degraded": operational_degraded,
                            "fail": operational_fail},
            "retrieval_observability": retrieval_observability,
            "root_causes": dict(observed_causes), "observation_only_root_causes": dict(observation_causes),
            "execution_failures": list(grouped_failures.values()),
            "failures": {name: sum(n for code, n in observed_causes.items() if code.startswith(prefix)) for name, prefix in (
                ("extraction", "EXTRACTION_"), ("taxonomy", "TAXONOMY_"),
                ("routing", "ROUTER_"), ("retrieval", "RETRIEVAL_"),
                ("handoff", "HANDOFF_"), ("validator", "LLM_"), ("grounding", "GROUNDING_"),
                ("consensus", "CONSENSUS_"), ("technical", "TECHNICAL_"),
                ("evidence_coherence", "VERDICT_EVIDENCE_"), ("undetermined", "UNDETERMINED"))}}


def persist(directory: Path, rows: list[dict], kind: str, manifest: dict, *, initialized=False):
    if not initialized:
        directory.mkdir(parents=True, exist_ok=False)
    for row in rows:
        write_json(directory / (row["run_id"] + ".json"), row)
    report = llm_report(rows) if kind == "llm" else pipeline_report(rows)
    write_json(directory / "manifest.json", manifest)
    write_json(directory / "report.json", report)
    lines = ["# " + report["report"], "", "```json", __import__("json").dumps(report, ensure_ascii=False, indent=2), "```", ""]
    if kind == "pipeline":
        if report.get("execution_failures"):
            lines += ["## Execution failures", "",
                      "| Stage | Diagnostic | Order | Affected cases | Reason |",
                      "|---|---|---|---|---|"]
            for failure in report["execution_failures"]:
                cells = [failure.get("stage"), failure.get("diagnostic_code"), failure.get("order_id"),
                         ", ".join(failure.get("affected_cases") or []), failure.get("reason")]
                lines.append("| " + " | ".join(str(c if c is not None else "—").replace("|", "\\|").replace("\n", " ") for c in cells) + " |")
            lines += [""]
        lines += ["| Case | Scope | Mode | Validator | Expected | Verdict | Extraction | Routing | Retrieval | Handoff | Grounding | Root cause |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for row in rows:
            m = row["metrics"]
            scope = "OBSERVATION_ONLY" if row.get("provenance", {}).get("scoring_eligible") is False else "SCORED"
            cells = [row["case_id"], scope, row["execution_mode"], row["validator"].get("id"),
                     row["expected"]["expected_verdict"] if scope == "SCORED" else None,
                     m["validation"]["verdict"], m["extraction"]["status"], m["routing"]["status"],
                     m["retrieval"]["status"], m["handoff"]["status"],
                     m["grounding"]["status"], row["root_cause"]["code"]]
            lines.append("| " + " | ".join(str(c if c is not None else "—").replace("|", "\\|").replace("\n", " ") for c in cells) + " |")
    (directory / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
