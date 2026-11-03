#!/usr/bin/env python3
"""Run GenerateAssertions comparisons directly against OpenRouter.

Only this test-side runner owns HTTP calls and metrics.  It imports production
prompt/schema code read-only at execution time; it never calls an Assermetry
endpoint, Kafka, databases, or Kubernetes.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES = ROOT / "tests/data/benchmark/resources/cases/official-gold-v0"
DEFAULT_ARTIFACTS = ROOT / "tests/data/evaluation/artifacts"
CATALOG_URL = "https://openrouter.ai/api/v1/models"
CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
CONFIGURATIONS = (
    {"id": "B0", "model": "openai/gpt-5-nano", "reasoning_effort": None},
    {"id": "B1", "model": "openai/gpt-5-nano", "reasoning_effort": "minimal"},
    {"id": "B2", "model": "openai/gpt-4.1-nano", "reasoning_effort": None},
    {"id": "B3", "model": "mistralai/mistral-small-3.2-24b-instruct", "reasoning_effort": None},
    {"id": "B4", "model": "google/gemini-3.1-flash-lite", "reasoning_effort": None},
)


class BenchmarkError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BenchmarkError(f"No se pudo leer JSON: {path}") from exc
    if not isinstance(value, dict):
        raise BenchmarkError(f"Se esperaba un objeto JSON: {path}")
    return value


def configurations(excluded_ids: set[str] | None = None) -> list[dict[str, Any]]:
    """Return the requested matrix without mutating the fixed experiment set."""
    excluded = excluded_ids or set()
    return [dict(item) for item in CONFIGURATIONS if item["id"] not in excluded]


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Test-side equivalent of the current OpenRouter schema normalisation."""
    clone = json.loads(json.dumps(schema))
    def visit(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, dict):
            node.pop("default", None)
            all_of = node.pop("allOf", None)
            if isinstance(all_of, list) and len(all_of) == 1 and isinstance(all_of[0], dict):
                node.update({key: value for key, value in all_of[0].items() if key not in node})
            elif all_of is not None:
                node["allOf"] = all_of
            for value in list(node.values()):
                visit(value)
            if isinstance(node.get("properties"), dict):
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
    visit(clone)
    return clone


def request_payload(prompt: str, schema: dict[str, Any], configuration: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "model": configuration["model"],
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": str(schema.get("title") or "AssertionBatch")[:64], "strict": True,
            "schema": strict_schema(schema),
        }},
        "provider": {"require_parameters": True},
    }
    if configuration.get("reasoning_effort") is not None:
        payload["reasoning"] = {"effort": configuration["reasoning_effort"]}
    return payload


def parse_usage(body: dict[str, Any]) -> dict[str, Any]:
    """Keep absent OpenRouter values null, never coerce them to zero."""
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    prompt_details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
    completion_details = usage.get("completion_tokens_details") if isinstance(usage.get("completion_tokens_details"), dict) else {}
    return {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "reasoning_tokens": completion_details.get("reasoning_tokens"),
        "cached_tokens": prompt_details.get("cached_tokens"),
        "cost_usd": usage.get("cost"),
        "raw_usage": usage or None,
    }


def response_content(body: dict[str, Any]) -> str:
    try:
        return str(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise BenchmarkError("OpenRouter devolvió una respuesta sin choices[0].message.content") from exc


def catalog(url: str = CATALOG_URL) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            value = json.loads(response.read())
    except Exception as exc:
        raise BenchmarkError(f"No se pudo consultar el catálogo OpenRouter: {type(exc).__name__}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("data"), list):
        raise BenchmarkError("El catálogo OpenRouter no contiene data[]")
    return value


def estimated_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def price(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def model_index(catalogue: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in catalogue.get("data", []) if isinstance(item, dict) and item.get("id")}


def compatibility(model: dict[str, Any] | None, configuration: dict[str, Any]) -> str | None:
    if model is None:
        return "MODEL_NOT_IN_CATALOG"
    supported = model.get("supported_parameters")
    if not isinstance(supported, list) or "response_format" not in supported:
        return "STRICT_JSON_SCHEMA_NOT_ADVERTISED"
    if configuration.get("reasoning_effort") and not any(str(value).startswith("reasoning") for value in supported):
        return "REASONING_EFFORT_NOT_ADVERTISED"
    return None


def plan(cases: list[dict[str, Any]], catalogue: dict[str, Any], repetitions: int,
         completion_token_estimate: int, prompt_builder: Callable[[str], str],
         selected_configurations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    models = model_index(catalogue)
    rows, total = [], 0.0
    selected = selected_configurations if selected_configurations is not None else configurations()
    for configuration in selected:
        model = models.get(configuration["model"])
        prompt_tokens = sum(estimated_tokens(prompt_builder(case["news"])) for case in cases) * repetitions
        completion_tokens = completion_token_estimate * len(cases) * repetitions
        pricing = model.get("pricing", {}) if model else {}
        input_rate, output_rate = price(pricing.get("prompt")), price(pricing.get("completion"))
        probe_prompt_tokens = estimated_tokens(prompt_builder(cases[0]["news"])) if cases else 0
        probe_cost = None if input_rate is None or output_rate is None else round(
            probe_prompt_tokens * input_rate + completion_token_estimate * output_rate, 10
        )
        estimate = None if input_rate is None or output_rate is None else round(prompt_tokens * input_rate + completion_tokens * output_rate, 10)
        if estimate is not None:
            total += estimate + (probe_cost or 0)
        rows.append({**configuration, "compatibility_error": compatibility(model, configuration),
                     "prompt_tokens_estimate": prompt_tokens, "completion_tokens_estimate": completion_tokens,
                     "estimated_cost_usd": estimate, "preflight_cost_estimate_usd": probe_cost})
    result = {"schema_version": "generate-assertions-isolated-plan-v1", "cases": len(cases),
              "repetitions": repetitions, "models": rows, "executions": len(cases) * len(selected) * repetitions,
              "preflight_provider_calls": len(selected),
              "minimum_provider_calls": len(cases) * len(selected) * repetitions + len(selected),
              "estimated_total_cost_usd": round(total, 10),
              "warning": "Retries and one Pydantic repair per execution can increase calls and cost."}
    result["plan_hash"] = sha256(result)
    return result


def load_target():
    sys.path.insert(0, str(ROOT / "api"))
    spec = importlib.util.spec_from_file_location("benchmark_generate_assertions", ROOT / "api/generate-asertions/main.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


async def post_json(url: str, api_key: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    def send() -> dict[str, Any]:
        request = urllib.request.Request(url, data=canonical(payload).encode(), method="POST", headers={
            "Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json",
            "HTTP-Referer": "https://trust-news", "X-Title": "TrustNews GenerateAssertions Benchmark",
        })
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    return await asyncio.to_thread(send)


class CappedPoster:
    """Enforce a campaign-wide HTTP cap, including retries and repairs."""
    def __init__(self, limit: int, delegate=post_json, initial_calls: int = 0):
        self.limit, self.delegate, self.calls = limit, delegate, initial_calls

    async def __call__(self, *args, **kwargs):
        if self.calls >= self.limit:
            raise BenchmarkError(f"MAX_PROVIDER_CALLS_REACHED ({self.limit})")
        self.calls += 1
        print(json.dumps({"event": "provider_call.start", "provider_call_number": self.calls}, ensure_ascii=False), flush=True)
        return await self.delegate(*args, **kwargs)


async def provider_call(post: Callable[..., Awaitable[dict[str, Any]]], url: str, key: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        body = await post(url, key, payload, timeout)
        result = {"status": "COMPLETED", "duration_seconds": round(time.monotonic() - started, 6),
                "response_id": body.get("id"), "usage": parse_usage(body), "content": response_content(body)}
        print(json.dumps({"event": "provider_call.complete", "duration_seconds": result["duration_seconds"]}), flush=True)
        return result
    except Exception as exc:
        result = {"status": "FAILED", "duration_seconds": round(time.monotonic() - started, 6),
                "error_type": type(exc).__name__, "error": str(exc)[:300], "usage": {}}
        print(json.dumps({"event": "provider_call.failed", "error_type": result["error_type"]}), flush=True)
        return result


async def structured_generation(target, configuration: dict[str, Any], news: str, *, post=post_json,
                                url: str, key: str, timeout: float, attempts: int) -> dict[str, Any]:
    """Mirror production's transport retry + single guided Pydantic repair in tests only."""
    schema = target.get_assertions_schema()
    calls: list[dict[str, Any]] = []
    async def attempt(prompt: str) -> dict[str, Any]:
        payload = request_payload(prompt, schema, configuration)
        for _ in range(attempts):
            call = await provider_call(post, url, key, payload, timeout)
            calls.append({key: value for key, value in call.items() if key != "content"})
            if call["status"] == "COMPLETED":
                return call
        return call
    total_started = time.monotonic()
    first = await attempt(target.build_assertions_prompt(news))
    if first["status"] != "COMPLETED":
        return result_failure(calls, total_started, first)
    parse_started = time.monotonic()
    try:
        batch = target.AssertionBatch.model_validate(json.loads(first["content"]))
        repaired = False
    except Exception as validation_error:
        repaired = True
        repair = await attempt(target.build_assertions_repair_prompt(first["content"], str(validation_error)))
        if repair["status"] != "COMPLETED":
            return result_failure(calls, total_started, repair, repair_used=True)
        try:
            batch = target.AssertionBatch.model_validate(json.loads(repair["content"]))
        except Exception as repair_error:
            return result_failure(calls, total_started, repair, repair_used=True, error=repair_error)
    parse_seconds = time.monotonic() - parse_started
    assertions = [item.model_dump(mode="json") for item in target.parse_assertions_content(batch.model_dump(mode="json"))]
    real_costs = [call["usage"].get("cost_usd") for call in calls if isinstance(call.get("usage"), dict)]
    return {"status": "COMPLETED", "duration_seconds": round(time.monotonic() - total_started, 6),
            "parse_validation_seconds": round(parse_seconds, 6), "repair_used": repaired,
            "assertion_count": len(assertions), "assertions": assertions, "provider_calls": calls,
            "provider_call_count": len(calls), "cost_real_usd": round(sum(cost for cost in real_costs if isinstance(cost, (int, float))), 10)
            if any(cost is not None for cost in real_costs) else None}


def result_failure(calls: list[dict[str, Any]], started: float, last: dict[str, Any], *, repair_used=False,
                   error: Exception | None = None) -> dict[str, Any]:
    return {"status": "FAILED", "duration_seconds": round(time.monotonic() - started, 6), "repair_used": repair_used,
            "parse_validation_seconds": None, "assertion_count": 0, "provider_calls": calls,
            "provider_call_count": len(calls), "cost_real_usd": None,
            "error_type": type(error).__name__ if error else last.get("error_type"),
            "error": str(error)[:300] if error else last.get("error")}


def quality(case: dict[str, Any], assertions: list[dict[str, Any]]) -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "tests")); sys.path.insert(0, str(ROOT / "api"))
    from evaluation.core.common_metrics import match_assertions
    matches = match_assertions(case, assertions)
    compatible = [row for row in matches if row["semantic_match_status"] == "COMPATIBLE"]
    expected = case["assertions"]
    recall = len(compatible) / len(expected) if expected else None
    precision = len(compatible) / len(assertions) if assertions else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else 0.0
    expected_by_id = {row["id"]: row for row in expected}
    category = topic = kind = context_hits = context_total = 0
    for match in compatible:
        actual, gold = assertions[match["generated_index"]], expected_by_id[match["expected_id"]]
        category += int(bool(match["category_match"]))
        topic += int(actual.get("topic_code") == gold.get("expected_topic_code"))
        accepted = {gold.get("expected_evidence_kind"), *(gold.get("accepted_evidence_kinds") or [])}
        kind += int(actual.get("evidence_kind") in accepted)
        wanted, actual_context = gold.get("expected_context") or {}, actual.get("context") or {}
        rendered = json.dumps(actual_context, ensure_ascii=False).lower()
        for field in ("entities", "locations", "temporal_context"):
            for value in wanted.get(field) or []:
                context_total += 1; context_hits += int(str(value).lower() in rendered)
        for field, value in (wanted.get("jurisdiction") or {}).items():
            context_total += 1; context_hits += int((actual_context.get("jurisdiction") or {}).get(field) == value)
    denominator = len(compatible)
    return {"extraction": {"precision": round(precision, 6), "recall": round(recall, 6) if recall is not None else None,
                             "f1": round(f1, 6), "omitted": len(expected) - len(compatible),
                             "invented_or_extra": len(assertions) - len(compatible),
                             "duplicates": len(assertions) - len({str(x.get("text") or "").lower() for x in assertions}),
                             "semantic_conflicts": [row for row in matches if row["semantic_match_status"] == "INCOMPATIBLE"]},
            "classification": {"category_accuracy": ratio(category, denominator), "topic_code_accuracy": ratio(topic, denominator),
                               "evidence_kind_accuracy": ratio(kind, denominator), "taxonomy_compatibility": "NOT_EVALUATED"},
            "context": {"coverage": ratio(context_hits, context_total) if context_total else "NOT_EVALUATED",
                        "roles": "NOT_EVALUATED", "origin": "NOT_EVALUATED", "search_hints": "NOT_EVALUATED"}}


def ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def percentile(values: list[float], fraction: float) -> float | None:
    return round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)], 6) if values else None


def aggregate(rows: list[dict[str, Any]], selected_configurations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    result = {}
    for config in selected_configurations if selected_configurations is not None else configurations():
        sample = [row for row in rows if row["configuration_id"] == config["id"]]
        complete = [row for row in sample if row["status"] == "COMPLETED"]
        durations = [row["duration_seconds"] for row in sample]
        f1s = [row["quality"]["extraction"]["f1"] for row in complete if row.get("quality")]
        calls = [call for row in sample for call in row.get("provider_calls", [])]
        def sum_usage(field):
            values = [call.get("usage", {}).get(field) for call in calls]
            present = [value for value in values if isinstance(value, int)]
            return sum(present) if present else None
        # A failed repair can still contain a billable first response.  Use the
        # provider-call ledger, which is authoritative for every outcome.
        costs = [call.get("usage", {}).get("cost_usd") for call in calls]
        costs = [cost for cost in costs if isinstance(cost, (int, float))]
        result[config["id"]] = {"model": config["model"], "runs": len(sample), "success_rate": ratio(len(complete), len(sample)),
            "error_rate": ratio(len(sample) - len(complete), len(sample)), "repair_rate": ratio(sum(bool(row.get("repair_used")) for row in sample), len(sample)),
            "duration_seconds": {"p50": percentile(durations, .5), "p95": percentile(durations, .95), "mean": round(statistics.fmean(durations), 6) if durations else None,
                                 "min": min(durations) if durations else None, "max": max(durations) if durations else None,
                                 "stdev": round(statistics.stdev(durations), 6) if len(durations) > 1 else None},
            "tokens": {name: sum_usage(name) for name in ("prompt_tokens", "completion_tokens", "reasoning_tokens", "cached_tokens", "total_tokens")},
            "cost_real_usd": round(sum(costs), 10) if costs else None, "extraction_f1": round(statistics.fmean(f1s), 6) if f1s else "NOT_EVALUATED",
            "p95_note": "Five repetitions are an indicative, not robust, p95 estimate."}
    return result


def save_reports(output: Path, summary: dict[str, Any]) -> None:
    columns = ["configuration", "model", "p50", "p95", "input_tokens", "output_tokens", "reasoning_tokens", "cost_real_usd", "f1", "repairs"]
    with (output / "comparison.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns); writer.writeheader()
        for identifier, row in summary.items():
            writer.writerow({"configuration": identifier, "model": row["model"], "p50": row["duration_seconds"]["p50"], "p95": row["duration_seconds"]["p95"],
                             "input_tokens": row["tokens"]["prompt_tokens"], "output_tokens": row["tokens"]["completion_tokens"],
                             "reasoning_tokens": row["tokens"]["reasoning_tokens"], "cost_real_usd": row["cost_real_usd"],
                             "f1": row["extraction_f1"], "repairs": row["repair_rate"]})
    table = ["# Benchmark aislado de GenerateAssertions", "", "p95 es indicativo con cinco repeticiones.", "",
             "| Modelo | p50 | p95 | Input tokens | Output tokens | Reasoning tokens | Coste real | F1 | Reparaciones |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for identifier, row in summary.items():
        table.append(f"| {identifier} {row['model']} | {row['duration_seconds']['p50']} | {row['duration_seconds']['p95']} | {row['tokens']['prompt_tokens']} | {row['tokens']['completion_tokens']} | {row['tokens']['reasoning_tokens']} | {row['cost_real_usd']} | {row['extraction_f1']} | {row['repair_rate']} |")
    (output / "report.md").write_text("\n".join(table) + "\n", encoding="utf-8")


def recorded_provider_calls(output: Path) -> int:
    """Resume safely: previously persisted calls consume the same hard cap."""
    total = 0
    for path in list((output / "preflight").glob("*.json")) + list((output / "runs").glob("*.json")):
        try:
            total += int(read_json(path).get("provider_call_count") or 0)
        except BenchmarkError:
            raise BenchmarkError(f"No se puede reanudar: artefacto inválido {path}")
    return total


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("plan", "run")); p.add_argument("--dataset", type=Path, default=DEFAULT_CASES)
    p.add_argument("--catalog", type=Path); p.add_argument("--catalog-cache", type=Path,
                   help="Optional path where a freshly fetched public catalog is persisted for later resumptions")
    p.add_argument("--repetitions", type=int, default=5)
    p.add_argument("--estimated-completion-tokens", type=int, default=1200); p.add_argument("--max-cost-usd", type=float)
    p.add_argument("--approve-plan"); p.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS); p.add_argument("--campaign-id")
    p.add_argument("--attempts", type=int, default=3); p.add_argument("--timeout", type=float, default=60)
    p.add_argument("--case-limit", type=int, help="Deterministic prefix of gold cases for a bounded sample")
    p.add_argument("--max-provider-calls", type=int, help="Hard ceiling across preflight, retries and repairs")
    p.add_argument("--exclude-configuration", action="append", default=[], metavar="ID",
                   help="Exclude a matrix configuration by ID (repeatable; for example B4)")
    p.add_argument("--max-new-executions", type=int,
                   help="Persist and stop after this many newly attempted primary executions; useful for resumable bounded runs")
    p.add_argument("--max-new-preflights", type=int,
                   help="Persist and stop after this many newly attempted preflights; useful for resumable bounded runs")
    p.add_argument("--preflight-only", action="store_true",
                   help="Run only the per-configuration compatibility preflights, then persist and stop")
    return p


async def run(args) -> int:
    if args.repetitions < 1 or args.attempts < 1 or args.estimated_completion_tokens < 1: raise BenchmarkError("Valores de ejecución inválidos")
    if args.case_limit is not None and args.case_limit < 1: raise BenchmarkError("--case-limit debe ser positivo")
    if args.max_provider_calls is not None and args.max_provider_calls < 1: raise BenchmarkError("--max-provider-calls debe ser positivo")
    if args.max_new_executions is not None and args.max_new_executions < 1: raise BenchmarkError("--max-new-executions debe ser positivo")
    if args.max_new_preflights is not None and args.max_new_preflights < 1: raise BenchmarkError("--max-new-preflights debe ser positivo")
    unknown_exclusions = set(args.exclude_configuration) - {item["id"] for item in CONFIGURATIONS}
    if unknown_exclusions: raise BenchmarkError(f"Configuraciones desconocidas: {', '.join(sorted(unknown_exclusions))}")
    selected_configurations = configurations(set(args.exclude_configuration))
    if not selected_configurations: raise BenchmarkError("No queda ninguna configuración para ejecutar")
    sys.path.insert(0, str(ROOT / "tests")); from evaluation.core.datasets import load_datasets
    cases = load_datasets([str(args.dataset)]); cases = cases[:args.case_limit] if args.case_limit else cases; target = load_target()
    catalogue = read_json(args.catalog) if args.catalog else catalog()
    if args.catalog_cache and not args.catalog:
        write_json(args.catalog_cache, catalogue)
    current_plan = plan(cases, catalogue, args.repetitions, args.estimated_completion_tokens, target.build_assertions_prompt, selected_configurations)
    print(json.dumps(current_plan, ensure_ascii=False, indent=2))
    if args.command == "plan": return 0
    if args.approve_plan != current_plan["plan_hash"]: raise BenchmarkError("Ejecute primero plan y pase su plan_hash con --approve-plan; no se hicieron llamadas facturables.")
    if args.max_cost_usd is None: raise BenchmarkError("--max-cost-usd explícito es obligatorio para ejecutar llamadas facturables.")
    if current_plan["estimated_total_cost_usd"] > args.max_cost_usd: raise BenchmarkError("La estimación supera --max-cost-usd; no se hicieron llamadas facturables.")
    if any(row["compatibility_error"] for row in current_plan["models"]): raise BenchmarkError("El catálogo no confirma la compatibilidad requerida.")
    key = os.getenv("OPENROUTER_API_KEY");
    if not key: raise BenchmarkError("OPENROUTER_API_KEY no está configurada; no se generan resultados simulados.")
    output = args.artifacts_root / (args.campaign_id or f"generate-assertions-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}")
    output.mkdir(parents=True, exist_ok=True); manifest_path = output / "manifest.json"
    capped_post = (CappedPoster(args.max_provider_calls, initial_calls=recorded_provider_calls(output))
                   if args.max_provider_calls else post_json)
    manifest = read_json(manifest_path) if manifest_path.exists() else {"schema_version": "generate-assertions-isolated-v1", "status": "RUNNING", "created_at": now(), "plan": current_plan,
        "git_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
        "dataset": [{"id": item["id"], "sha256": sha256(item)} for item in cases], "prompt_sha256": sha256(target.build_assertions_prompt("__BENCHMARK_TEXT__")), "schema_sha256": sha256(target.get_assertions_schema()), "configurations": selected_configurations, "runs": []}
    write_json(manifest_path, manifest); rows = []; preflight_spent = 0.0; failed_preflights = []
    # A single paid, structured call per model catches routing/schema failures
    # before the complete campaign.  It is deliberately outside quality stats.
    stopped_by_preflight_limit = False
    new_preflights = 0
    for configuration in selected_configurations:
        probe_file = output / "preflight" / f"{configuration['id']}.json"
        probe = read_json(probe_file) if probe_file.exists() else None
        if probe is None:
            if args.max_new_preflights is not None and new_preflights >= args.max_new_preflights:
                stopped_by_preflight_limit = True; break
            if preflight_spent >= args.max_cost_usd: raise BenchmarkError("Presupuesto agotado antes del preflight.")
            probe = await structured_generation(target, configuration, cases[0]["news"], post=capped_post, url=os.getenv("OPENROUTER_API_URL", CHAT_URL), key=key, timeout=args.timeout, attempts=args.attempts)
            new_preflights += 1
            write_json(probe_file, probe)
        if probe.get("status") != "COMPLETED":
            failed_preflights.append(configuration["id"])
        preflight_spent += probe.get("cost_real_usd") or 0
    if failed_preflights:
        manifest["status"] = "PREFLIGHT_FAILED"; write_json(manifest_path, manifest)
        raise BenchmarkError(f"Preflight falló para {', '.join(failed_preflights)}; no se inició la campaña completa.")
    if stopped_by_preflight_limit:
        manifest["status"] = "PREFLIGHT_PARTIAL"
        summary = aggregate([], selected_configurations)
        write_json(output / "metrics.json", summary); write_json(manifest_path, manifest); save_reports(output, summary)
        print(json.dumps({"campaign": str(output), "status": manifest["status"], "runs": 0,
                          "provider_calls": capped_post.calls if isinstance(capped_post, CappedPoster) else None}, ensure_ascii=False)); return 0
    if args.preflight_only:
        manifest["status"] = "PREFLIGHT_COMPLETED"
        summary = aggregate([], selected_configurations)
        write_json(output / "metrics.json", summary); write_json(manifest_path, manifest); save_reports(output, summary)
        print(json.dumps({"campaign": str(output), "status": manifest["status"], "runs": 0,
                          "provider_calls": capped_post.calls if isinstance(capped_post, CappedPoster) else None}, ensure_ascii=False)); return 0
    stopped_by_execution_limit = False
    new_executions = 0
    for repetition in range(1, args.repetitions + 1):
        for index, case in enumerate(cases):
            offset = (index + repetition - 1) % len(selected_configurations)
            for configuration in selected_configurations[offset:] + selected_configurations[:offset]:
                file = output / "runs" / f"{case['id']}--{configuration['id']}--r{repetition}.json"
                if file.exists(): rows.append(read_json(file)); continue
                if args.max_new_executions is not None and new_executions >= args.max_new_executions:
                    stopped_by_execution_limit = True; break
                consumed = preflight_spent + sum(row.get("cost_real_usd") or 0 for row in rows)
                if consumed >= args.max_cost_usd: manifest["status"] = "BUDGET_EXHAUSTED"; break
                row = await structured_generation(target, configuration, case["news"], post=capped_post, url=os.getenv("OPENROUTER_API_URL", CHAT_URL), key=key, timeout=args.timeout, attempts=args.attempts)
                new_executions += 1
                row.update(case_id=case["id"], configuration_id=configuration["id"], repetition=repetition)
                if row["status"] == "COMPLETED": row["quality"] = quality(case, row["assertions"])
                write_json(file, row); manifest["runs"].append(str(file.relative_to(output))); rows.append(row); write_json(manifest_path, manifest)
            if manifest.get("status") == "BUDGET_EXHAUSTED" or stopped_by_execution_limit: break
        if manifest.get("status") == "BUDGET_EXHAUSTED" or stopped_by_execution_limit: break
    summary = aggregate(rows, selected_configurations)
    manifest["status"] = (manifest.get("status") if manifest.get("status") == "BUDGET_EXHAUSTED"
                          else "PARTIAL" if stopped_by_execution_limit else "COMPLETED")
    write_json(output / "metrics.json", summary); write_json(manifest_path, manifest); save_reports(output, summary)
    print(json.dumps({"campaign": str(output), "status": manifest["status"], "runs": len(rows),
                      "provider_calls": capped_post.calls if isinstance(capped_post, CappedPoster) else None}, ensure_ascii=False)); return 0


def main(argv: list[str] | None = None) -> int:
    try: return asyncio.run(run(parser().parse_args(argv)))
    except BenchmarkError as exc: print(f"ERROR: {exc}", file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
