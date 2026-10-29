import json

from evaluation.pipeline.compare_modes import compare_campaigns


def _campaign(parent, name, *, citable, cached=False, assertion="same assertion", mode="DIRECT"):
    directory = parent / name
    directory.mkdir()
    run_id = "123e4567-e89b-12d3-a456-426614174000"
    (directory / "manifest.json").write_text(json.dumps({
        "schema_version": "evaluation-manifest-v1", "runs": [run_id],
    }))
    (directory / "cost-rates.json").write_text(json.dumps({
        "schema_version": "evaluation-cost-rates-v1", "currency": "USD", "llm": [], "search": [],
    }))
    (directory / f"{run_id}.json").write_text(json.dumps({
        "dataset_hash": "data-hash", "case_id": "case-1", "assertion_id": "1",
        "assertion": {"text": assertion},
        "validator": {"id": "validator-1", "config_version": 1,
                      "evidence_search_strategy": "LOCAL"},
        "retrieval": {"provider_trace": {"summary": {"calls_attempted": 1}},
                      "extraction_policy": {"mode": mode}},
        "metrics": {"retrieval": {"documents_citable": citable,
                                  "reference_source_citable": bool(citable),
                                  "response_cached": cached, "http_requests": 1},
                    "validation": {"correct": bool(citable)},
                    "grounding": {"verified_count": citable, "rejected_count": 0}},
        "timings": {"retrieval_seconds": 1.5},
    }))
    return directory


def test_mode_comparison_requires_same_assertions_and_cold_responses(tmp_path):
    direct = _campaign(tmp_path, "direct", citable=0)
    smart = _campaign(tmp_path, "smart", citable=1, mode="SMART")
    report = compare_campaigns(direct, smart)
    assert report["status"] == "COMPARABLE"
    assert report["smart_minus_direct"]["citable_sources_mean"] == 1
    assert report["smart_minus_direct"]["reference_citable_rate"] == 1
    _campaign(tmp_path, "cached", citable=1, cached=True, mode="SMART")
    assert compare_campaigns(direct, tmp_path / "cached")["status"] == "INCOMPLETE"
    _campaign(tmp_path, "different", citable=1, assertion="different assertion", mode="SMART")
    assert compare_campaigns(direct, tmp_path / "different")["matched_groups"] == 0
