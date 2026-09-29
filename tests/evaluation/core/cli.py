"""Shared CLI wiring; execution is common, reports and diagnostics are distinct."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import uuid

from evaluation import ROOT
from .artifacts import EvaluationError, read_json, canonical_json, sha256_text, write_json
from .datasets import load_datasets
from .execution import execute, validator_config
from .evidence import replay_bundle
from .orders import results_from_order
from .models import CaseResult
from .order_execution import publish_and_wait, legacy_client
from .reporting import persist
from .services import HttpServices
from evaluation.pipeline.metrics import evaluate
from evaluation.pipeline.root_cause import diagnose
from common.utils.validation_prompt import DEFAULT_RAG_PROMPT

MODES = {"full": "FULL_PIPELINE", "gold-domains": "GOLD_DOMAINS", "gold-evidence": "GOLD_EVIDENCE", "replay": "VALIDATOR_REPLAY"}


def trace(phase, **fields):
    """Emit concise, secret-free progress records for interactive evaluation runs."""
    parts = [f"phase={phase}"]
    for key, value in fields.items():
        if value is None:
            continue
        value = str(value).replace("\n", " ").replace("\r", " ").strip()
        parts.append(f"{key}={value or '-'}")
    print("EVALUATION_TRACE " + " ".join(parts), flush=True)


def parser(kind):
    p = argparse.ArgumentParser(description="LLM comparison" if kind == "llm" else "Assermetry pipeline diagnostics")
    p.add_argument("--dataset", action="append", default=[], help="Resource ID, JSON path or directory; repeatable")
    p.add_argument("--tag", action="append", default=[], help="All tags must match (AND)")
    p.add_argument("--mode", choices=MODES, default="gold-evidence" if kind == "llm" else "full")
    p.add_argument("--model", action="append", default=[], help="provider:model; repeatable")
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--repetitions", type=int, default=1)
    p.add_argument("--cache", choices=["COLD", "WARM", "FROZEN"])
    p.add_argument("--replay-artifact", type=Path)
    p.add_argument("--order", type=Path, help="Inspect an existing order.json; no network calls")
    p.add_argument("--publish", action="store_true", help="Run the existing LIGHT news pipeline with deployed validators")
    p.add_argument("--base-url", default="https://localhost:7443/backend")
    p.add_argument("--verify-tls", action=argparse.BooleanOptionalAction, default=False)
    p.add_argument("--result-timeout", type=float, default=600)
    p.add_argument("--counterfactuals", action="store_true", help="FULL + GOLD_DOMAINS + GOLD_EVIDENCE where annotated")
    p.add_argument("--router-url", default="http://localhost:8075")
    p.add_argument("--evidence-search-url", default="http://localhost:8074")
    p.add_argument("--prompt-file", type=Path, help="Use a specific deployed RAG template; only its hash is persisted")
    p.add_argument("--output", type=Path, help="New output directory; existing directories are never overwritten")
    p.add_argument("--analyze", type=Path, metavar="CAMPAIGN_DIR",
                   help="Analyze saved campaign artifacts offline; write analysis.json and analysis.md")
    p.add_argument("--validate-only", action="store_true", help="Validate resources without calling services or LLMs")
    return p


def main(kind, argv=None):
    p = parser(kind)
    args = p.parse_args(argv)
    try:
        if args.analyze:
            if (args.dataset or args.tag or args.model or args.order or args.publish or args.replay_artifact
                    or args.counterfactuals or args.validate_only or args.cache or args.prompt_file
                    or args.mode != ("gold-evidence" if kind == "llm" else "full") or args.repetitions != 1):
                raise EvaluationError("--analyze reads a saved campaign; omit execution and dataset flags")
            from evaluation.pipeline.analyze import analyze_campaign
            files = analyze_campaign(args.analyze, args.output)
            print(json.dumps({"analysis_json": str(files[0]), "analysis_markdown": str(files[1])},
                             ensure_ascii=False, indent=2))
            return 0
        if args.repetitions < 1:
            raise EvaluationError("repetitions must be positive")
        replay = read_json(args.replay_artifact) if args.replay_artifact else None
        if args.mode == "replay" and replay is None:
            raise EvaluationError("replay requires --replay-artifact")
        if replay and args.mode != "replay":
            raise EvaluationError("--replay-artifact requires --mode replay")
        if args.publish and (args.mode != "full" or args.model or args.cache or args.order or args.counterfactuals):
            raise EvaluationError("--publish uses the deployed LIGHT configuration; omit model/cache/order/counterfactuals")
        if args.counterfactuals and (args.mode != "full" or args.order):
            raise EvaluationError("--counterfactuals requires live --mode full")
        if args.order and (args.mode != "full" or args.model or args.cache or args.repetitions != 1):
            raise EvaluationError("--order is an offline FULL_PIPELINE import; omit model/cache/repetitions")
        if not args.dataset and not replay:
            raise EvaluationError("Provide --dataset or --replay-artifact")
        if replay:
            replay_bundle(replay)
        if replay and not args.dataset:
            datasets = [{"schema_version": 2, "id": replay.get("dataset_id") or "replay",
                         "news": replay["assertion"]["text"], "assertions": [replay["expected"]]}]
        else:
            datasets = load_datasets(args.dataset, args.tag)
        if args.validate_only:
            trace("validation.complete", kind=kind, datasets=len(datasets),
                  assertions=sum(len(d["assertions"]) for d in datasets))
            print(json.dumps({"datasets": len(datasets), "assertions": sum(len(d["assertions"]) for d in datasets)}))
            return 0
        configs = []
        for model in args.model:
            provider, separator, name = model.partition(":")
            if not separator:
                raise EvaluationError("--model must be provider:model")
            configs.append(validator_config(provider, name, args.temperature))
        if not configs and not args.order and not args.publish:
            raise EvaluationError("Provide at least one --model provider:model")
        if len({c["id"] for c in configs}) != len(configs):
            raise EvaluationError("Duplicate model; use --repetitions for stability runs")
        template = args.prompt_file.read_text(encoding="utf-8") if args.prompt_file else DEFAULT_RAG_PROMPT
        services = HttpServices(args.router_url, args.evidence_search_url)
        output = args.output or ROOT / "tests/evaluation/artifacts" / str(uuid.uuid4())
        output.mkdir(parents=True, exist_ok=False)
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, text=True, capture_output=True, check=False).stdout.strip()
        manifest = {"schema_version": "evaluation-manifest-v1", "status": "RUNNING", "git_commit": commit,
                    "git_dirty": bool(dirty), "created_at": datetime.now(timezone.utc).isoformat(),
                    "datasets": [{"id": d["id"], "sha256": sha256_text(canonical_json(d))} for d in datasets],
                    "validators": configs, "prompt_template_hash": sha256_text(template), "runs": [], "tags": args.tag}
        write_json(output / "manifest.json", manifest)
        trace("campaign.prepared", kind=kind, mode=MODES[args.mode],
              datasets=len(datasets), assertions=sum(len(d["assertions"]) for d in datasets),
              validators=len(configs), repetitions=args.repetitions)
        rows = []
        def record(row):
            rows.append(row)
            write_json(output / (row["run_id"] + ".json"), row)
            manifest["runs"].append(row["run_id"])
            write_json(output / "manifest.json", manifest)
            trace("run.persisted", run_id=row["run_id"], case_id=row["case_id"],
                  mode=row["execution_mode"], errors=len(row["errors"]))
        for dataset in datasets:
            if args.publish:
                for repetition in range(1, args.repetitions + 1):
                    parent_id = str(uuid.uuid4())
                    published = {}
                    try:
                        trace("repetition.start", parent_run_id=parent_id, dataset_id=dataset["id"],
                              repetition=repetition, mode="FULL_PIPELINE")
                        client, wait = legacy_client(args.base_url, args.verify_tls, 30)
                        trace("order.publish.start", parent_run_id=parent_id, dataset_id=dataset["id"])
                        def published_order(order_id):
                            published.update(order_id=order_id)
                            trace("order.publish.complete", parent_run_id=parent_id, order_id=order_id)
                            trace("order.poll.start", parent_run_id=parent_id, order_id=order_id,
                                  timeout_seconds=args.result_timeout)
                        order = publish_and_wait(
                            client, dataset, wait, timeout_seconds=args.result_timeout,
                            on_publish=published_order,
                            progress=lambda current, status, event: trace(
                                "order.poll", parent_run_id=parent_id, order_id=published.get("order_id"),
                                status=status or "UNKNOWN", last_event=event),
                        )
                        trace("order.terminal", parent_run_id=parent_id, order_id=published.get("order_id"),
                              status=order.get("status"))
                        write_json(output / (parent_id + "-order.json"), order)
                        trace("order.import.start", parent_run_id=parent_id, order_id=published.get("order_id"))
                        imported = results_from_order(dataset, order, parent_id)
                        trace("order.import.complete", parent_run_id=parent_id, results=len(imported))
                    except Exception as exc:
                        trace("repetition.failed", parent_run_id=parent_id, stage="ORDER_EXECUTION",
                              exception_type=type(exc).__name__)
                        imported = []
                        for expected in dataset["assertions"]:
                            failure = CaseResult(expected["id"], "FULL_PIPELINE", {"text": expected.get("text", "")}, expected,
                                dataset_id=dataset["id"], order_id=published.get("order_id"))
                            failure.errors = [{"stage": "ORDER_EXECUTION", "code": "TECHNICAL_ERROR", "exception_type": type(exc).__name__}]
                            failure.provenance = {"parent_run_id": parent_id, "origin": "persisted_order"}
                            imported.append(failure)
                    for result in imported:
                        row = result.to_dict()
                        row["provenance"]["repetition"] = repetition
                        record(row)
                continue
            if args.order:
                trace("order.import.start", dataset_id=dataset["id"], order=args.order)
                imported = results_from_order(dataset, read_json(args.order))
                trace("order.import.complete", dataset_id=dataset["id"], results=len(imported))
                for r in imported:
                    record(r.to_dict())
                continue
            for expected in dataset["assertions"]:
                for repetition in range(1, args.repetitions + 1):
                    for config in configs:
                        modes = [MODES[args.mode]]
                        if args.counterfactuals:
                            if expected.get("acceptable_domains"):
                                modes.append("GOLD_DOMAINS")
                            if "reference_evidence" in expected:
                                modes.append("GOLD_EVIDENCE")
                        for mode in modes:
                            cache = "FROZEN" if args.counterfactuals and mode == "GOLD_EVIDENCE" else args.cache
                            row = execute(dataset, expected, config, mode, services=services,
                                          cache_mode=cache, replay=replay, template=template,
                                          progress=trace).to_dict()
                            row["provenance"]["repetition"] = repetition
                            record(row)
        if kind == "pipeline":
            trace("consensus.start", runs=len(rows))
            from .consensus import attach_consensus
            attach_consensus(rows)
            trace("consensus.complete", runs=len(rows))
        trace("metrics.start", runs=len(rows))
        for row in rows:
            row["metrics"] = evaluate(row)
        trace("metrics.complete", runs=len(rows))
        # Within the same repetition only; avoid accidental cross-trial causal claims.
        trace("root_cause.start", runs=len(rows))
        for row in rows:
            peers = [r for r in rows if r.get("dataset_id") == row.get("dataset_id") and
                     r.get("provenance", {}).get("repetition") == row.get("provenance", {}).get("repetition")]
            row["root_cause"] = diagnose(row, peers)
        trace("root_cause.complete", runs=len(rows))
        manifest["status"] = "COMPLETED_WITH_ERRORS" if any(r["errors"] for r in rows) else "COMPLETED"
        trace("report.start", status=manifest["status"], runs=len(rows))
        report = persist(output, rows, kind, manifest, initialized=True)
        trace("campaign.complete", status=manifest["status"], runs=len(rows))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"EVALUATION_REPORT {output / 'report.md'}")
        return 1 if any(row["errors"] for row in rows) else 0
    except (EvaluationError, ValueError, OSError) as exc:
        # Known local configuration errors contain no provider request/response data.
        trace("campaign.failed", kind=kind, exception_type=type(exc).__name__)
        p.error(str(exc))
