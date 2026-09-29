"""Write immutable per-run artifacts; the two reports keep separate purposes."""

from collections import Counter
from pathlib import Path
import statistics

from .artifacts import write_json


def llm_report(rows):
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
    return {"report": "llm-benchmark", "models": models, "comparison_conditions": conditions}


def pipeline_report(rows):
    # Count assertions, not validators or counterfactual executions.
    groups = {}
    for row in rows:
        groups.setdefault((row.get("dataset_id"), row["case_id"], row.get("provenance", {}).get("repetition", 1)), []).append(row)
    correct = incorrect = not_evaluated = 0
    causes = Counter()
    for items in groups.values():
        full = [r for r in items if r["execution_mode"] == "FULL_PIPELINE"]
        for code in {r["root_cause"]["code"] for r in (full or items)} - {None}:
            causes[code] += 1
        if not full:
            not_evaluated += 1
            continue
        consensus = next((r["metrics"]["consensus"] for r in full if r["metrics"]["consensus"]["status"] != "NOT_EVALUATED"), None)
        observed = [r["metrics"]["validation"]["correct"] for r in full]
        if consensus:
            passed = consensus["status"] == "CONSENSUS_PASS"
        elif len(full) == 1:
            passed = observed[0]
        else:
            passed = None  # Multiple validators without an observed consensus.
        if any(r["errors"] or r["metrics"]["extraction"]["status"] == "EXTRACTION_ERROR"
               or r["metrics"]["handoff"]["status"] == "HANDOFF_EVIDENCE_MISMATCH" for r in full):
            passed = False
        if passed is None:
            not_evaluated += 1
        elif passed:
            correct += 1
        else:
            incorrect += 1
    return {"report": "pipeline-evaluation", "total_cases": len(groups), "executions": len(rows),
            "end_to_end_correct": correct, "end_to_end_incorrect": incorrect, "not_evaluated": not_evaluated,
            "root_causes": dict(causes),
            "failures": {name: sum(n for code, n in causes.items() if code.startswith(prefix)) for name, prefix in (
                ("extraction", "EXTRACTION_"), ("routing", "ROUTER_"), ("retrieval", "RETRIEVAL_"),
                ("handoff", "HANDOFF_"), ("validator", "LLM_"), ("grounding", "GROUNDING_"),
                ("consensus", "CONSENSUS_"), ("technical", "TECHNICAL_"), ("undetermined", "UNDETERMINED"))}}


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
        lines += ["| Case | Mode | Validator | Expected | Verdict | Routing | Retrieval | Handoff | Grounding | Root cause |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for row in rows:
            m = row["metrics"]
            cells = [row["case_id"], row["execution_mode"], row["validator"].get("id"), row["expected"]["expected_verdict"],
                     m["validation"]["verdict"], m["routing"]["status"], m["retrieval"]["status"], m["handoff"]["status"],
                     m["grounding"]["status"], row["root_cause"]["code"]]
            lines.append("| " + " | ".join(str(c if c is not None else "—").replace("|", "\\|").replace("\n", " ") for c in cells) + " |")
    (directory / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
