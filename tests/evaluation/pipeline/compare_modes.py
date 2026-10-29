"""Compare two saved retrieval campaigns on the same assertions and validators."""

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from evaluation.viewer.server import index_campaign


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _key(run):
    assertion = run.get("assertion") or {}
    validator = run.get("validator") or {}
    return (
        str(run.get("dataset_hash") or ""), str(run.get("case_id") or ""),
        str(assertion.get("text") or "").strip(), str(run.get("assertion_id") or ""),
        str(validator.get("id") or ""), str(validator.get("config_version") or ""),
        str(validator.get("evidence_search_strategy") or ""),
    )


def _runs(directory: Path):
    manifest = _json(directory / "manifest.json")
    if manifest.get("schema_version") != "evaluation-manifest-v1" or not manifest.get("runs"):
        raise ValueError(f"Invalid or empty campaign manifest: {directory}")
    groups = defaultdict(list)
    for run_id in manifest["runs"]:
        if not isinstance(run_id, str) or any(char not in "0123456789abcdef-" for char in run_id.lower()):
            raise ValueError(f"Invalid run ID in {directory}")
        run = _json(directory / f"{run_id}.json")
        groups[_key(run)].append(run)
    return groups


def _mean(values):
    values = [float(value) for value in values if isinstance(value, (int, float, bool))]
    return round(sum(values) / len(values), 6) if values else None


def _summary(runs):
    metrics = [run.get("metrics") or {} for run in runs]
    retrieval = [item.get("retrieval") or {} for item in metrics]
    grounding = [item.get("grounding") or {} for item in metrics]
    validation = [item.get("validation") or {} for item in metrics]
    traces = [(run.get("retrieval") or {}).get("provider_trace") or {} for run in runs]
    return {
        "runs": len(runs),
        "response_cache_hits": sum(bool(item.get("response_cached")) for item in retrieval),
        "citable_sources_mean": _mean(item.get("documents_citable") for item in retrieval),
        "reference_citable_rate": _mean(item.get("reference_source_citable") is True for item in retrieval),
        "lexical_reference_coverage_mean": _mean(item.get("lexical_reference_coverage") for item in retrieval),
        "verdict_correct_rate": _mean(item.get("correct") is True for item in validation),
        "verified_citations_mean": _mean(item.get("verified_count") for item in grounding),
        "rejected_citations_mean": _mean(item.get("rejected_count") for item in grounding),
        "retrieval_seconds_mean": _mean((run.get("timings") or {}).get("retrieval_seconds") for run in runs),
        "http_requests_mean": _mean(item.get("http_requests") for item in retrieval),
        "provider_search_calls_mean": _mean((trace.get("summary") or {}).get("calls_attempted") for trace in traces),
        "provider_extract_calls_mean": _mean(item.get("provider_extract_calls") for item in retrieval),
        "provider_extract_cost_usd_reported_mean": _mean(
            item.get("provider_extract_cost_usd_observed") for item in retrieval),
        "provider_extract_cost_usd_per_citable_source_mean": _mean(
            item.get("provider_extract_cost_usd_per_citable_source") for item in retrieval),
        "unknown_freshness_mean": _mean(item.get("documents_freshness_unknown") for item in retrieval),
        "direct_failures_recovered_mean": _mean(item.get("direct_failures_recovered_by_provider") for item in retrieval),
    }


def _rates_digest(directory: Path):
    path = directory / "cost-rates.json"
    if not path.exists():
        return None
    return hashlib.sha256(json.dumps(_json(path), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def compare_campaigns(direct: Path, smart: Path):
    direct, smart = direct.resolve(), smart.resolve()
    baseline, candidate = _runs(direct), _runs(smart)
    common = set(baseline) & set(candidate)
    matched = []
    mismatched_counts = 0
    for key in common:
        if len(baseline[key]) != len(candidate[key]):
            mismatched_counts += 1
            continue
        matched.append((baseline[key], candidate[key]))
    direct_runs = [run for left, _ in matched for run in left]
    smart_runs = [run for _, right in matched for run in right]
    direct_summary, smart_summary = _summary(direct_runs), _summary(smart_runs)
    direct_modes = {(run.get("retrieval") or {}).get("extraction_policy", {}).get("mode") for run in direct_runs}
    smart_modes = {(run.get("retrieval") or {}).get("extraction_policy", {}).get("mode") for run in smart_runs}
    rates_match = _rates_digest(direct) == _rates_digest(smart)
    direct_costs = index_campaign(direct.parent, direct.name).get("costs") or {}
    smart_costs = index_campaign(smart.parent, smart.name).get("costs") or {}
    comparable = (bool(matched) and direct_modes == {"DIRECT"} and smart_modes == {"SMART"}
                  and len(common) == len(baseline) == len(candidate)
                  and mismatched_counts == 0 and direct_summary["response_cache_hits"] == 0
                  and smart_summary["response_cache_hits"] == 0 and rates_match)
    deltas = {key: round(smart_summary[key] - direct_summary[key], 6)
              for key in direct_summary if key != "runs" and isinstance(direct_summary[key], (int, float))
              and isinstance(smart_summary[key], (int, float))}
    return {
        "schema_version": "evidence-mode-comparison-v1",
        "status": "COMPARABLE" if comparable else "INCOMPLETE",
        "matched_groups": len(matched), "direct_only_groups": len(baseline.keys() - candidate.keys()),
        "smart_only_groups": len(candidate.keys() - baseline.keys()),
        "unequal_repetition_groups": mismatched_counts, "rates_match": rates_match,
        "direct_modes": sorted(str(mode) for mode in direct_modes),
        "smart_modes": sorted(str(mode) for mode in smart_modes),
        "direct": {**direct_summary, "campaign_costs": direct_costs},
        "smart": {**smart_summary, "campaign_costs": smart_costs},
        "smart_minus_direct": deltas,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("direct", type=Path, help="DIRECT campaign directory")
    parser.add_argument("smart", type=Path, help="SMART campaign directory")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = compare_campaigns(args.direct, args.smart)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
