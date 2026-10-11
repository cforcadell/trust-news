"""The viewer reads saved diagnostics without modifying campaign artifacts."""

import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import urlopen
from http.server import ThreadingHTTPServer

from evaluation.viewer.server import _read_diagnostic, index_campaign, list_campaigns, make_handler


FIXTURE = Path(__file__).resolve().parents[1] / "data/evaluation/resources/viewer-fixtures/order-diagnostic-v1.json"
STATIC = Path(__file__).parent / "viewer/static"


def _campaign(tmp_path):
    directory = tmp_path / "fixture-campaign"
    directory.mkdir()
    (directory / "fixture-parent-viewer.json").write_bytes(FIXTURE.read_bytes())
    (directory / "manifest.json").write_text(json.dumps({"status": "COMPLETED", "created_at": "2026-10-01T00:00:00Z"}))
    return directory


def test_campaign_index_isolates_broken_snapshots(tmp_path):
    directory = _campaign(tmp_path)
    (directory / "broken-viewer.json").write_text("{invalid")
    indexed = index_campaign(tmp_path, "fixture-campaign")
    assert indexed["status"] == "COMPLETED"
    assert len(indexed["orders"]) == 1
    assert indexed["orders"][0]["assertions"] == 2
    assert indexed["orders"][0]["validations"] == 2
    assert indexed["orders"][0]["correct_validations"] == 1
    assert indexed["orders"][0]["findings"] == len(indexed["incidents"])
    assert {item["type"] for item in indexed["incidents"]} <= {"warning", "error"}
    assert len(indexed["errors"]) == 1
    assert list_campaigns(tmp_path)[0]["order_count"] == 1


def test_legacy_snapshot_is_enriched_from_result_without_rewriting_it(tmp_path):
    directory = _campaign(tmp_path)
    result = {"validator": {"validator_type": "RAG_EVIDENCE_VALIDATION",
                            "provider": "openrouter", "model": "model-a",
                            "evidence_search_strategy": "EXT_ONLY_OFFICIAL"}}
    (directory / "run-b.json").write_text(json.dumps(result), encoding="utf-8")

    diagnostic = _read_diagnostic(directory / "fixture-parent-viewer.json")
    validation = next(item for item in diagnostic["validations"] if item["run_id"] == "run-b")

    assert validation["validator"]["model"] == "model-a"
    assert validation["stages"]["router"]["execution_status"] == "SKIPPED"
    assert validation["stages"]["router"]["observations"]["skip_reason"] == "EXTERNAL_EVIDENCE_STRATEGY"
    persisted = json.loads((directory / "fixture-parent-viewer.json").read_text(encoding="utf-8"))
    assert "validator" not in persisted["validations"][1]


def test_http_navigation_and_missing_raw_artifact(tmp_path):
    _campaign(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(tmp_path))
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/api/campaigns") as response:
            campaigns = json.load(response)
        assert campaigns[0]["campaign_id"] == "fixture-campaign"
        with urlopen(base + "/api/campaigns/fixture-campaign/orders") as response:
            listing = json.load(response)
        assert listing["orders"][0]["order_id"] == "fixture-order"
        with urlopen(base + "/api/campaigns/fixture-campaign/orders/fixture-parent-viewer.json") as response:
            detail = json.load(response)
        assert detail["validations"][1]["stages"]["citations"]["assessment"] == "FAIL"
        assert detail["viewer_summary"]["validators_observed"] == 2
        with urlopen(base + "/") as response:
            assert b"Benchmark Viewer" in response.read()
        try:
            urlopen(base + "/api/campaigns/fixture-campaign/artifacts/run-a.json")
        except HTTPError as exc:
            assert exc.code == 404
        else:
            assert False, "missing raw artifact should return HTTP 404"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_static_navigation_uses_paginated_table_views():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")

    assert 'id="nav-campaigns"' in html
    assert 'id="nav-orders"' in html
    assert 'id="selected-campaign"' in html
    assert 'id="order-menu"' in html
    assert 'id="campaigns"' not in html
    assert 'id="orders"' not in html
    assert "renderCampaignIndex" in script
    assert "renderOrderIndex" in script
    assert "paginationControls" in script
    assert "filterHeader" in script
    assert "sortedEntries" in script
    assert "formatSavedDate" in script
    assert 'campaignView: "summary"' in script
    assert "renderOrderSummary" in script
    assert "Aserciones × validadores" in script
    assert 'campaigns: {key: "date", direction: "desc"}' in script


def test_campaign_orders_and_campaigns_are_sorted_by_saved_date(tmp_path):
    old = tmp_path / "old-campaign"
    new = tmp_path / "new-campaign"
    old.mkdir(); new.mkdir()
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for directory, campaign, created in [
            (old, "old-campaign", "2026-01-01T00:00:00Z"),
            (new, "new-campaign", "2026-03-01T00:00:00Z")]:
        document = json.loads(json.dumps(fixture))
        document["identity"]["campaign_id"] = campaign
        (directory / "fixture-parent-viewer.json").write_text(json.dumps(document), encoding="utf-8")
        (directory / "fixture-parent-order.json").write_text(json.dumps({
            "created_at": created, "updated_at": created}), encoding="utf-8")
        (directory / "manifest.json").write_text(json.dumps({
            "status": "COMPLETED", "created_at": created}), encoding="utf-8")

    assert [item["campaign_id"] for item in list_campaigns(tmp_path)] == [
        "new-campaign", "old-campaign"]
    indexed = index_campaign(tmp_path, "new-campaign")
    assert indexed["orders"][0]["created_at"] == "2026-03-01T00:00:00Z"
    assert indexed["incidents"][0]["created_at"] == "2026-03-01T00:00:00Z"


def test_campaign_with_report_but_without_viewer_snapshot_remains_visible(tmp_path):
    directory = tmp_path / "failed-campaign"
    directory.mkdir()
    (directory / "manifest.json").write_text(json.dumps({
        "status": "COMPLETED_WITH_ERRORS", "created_at": "2026-04-01T00:00:00Z"}),
        encoding="utf-8")
    (directory / "report.json").write_text(json.dumps({
        "total_cases": 3, "end_to_end_correct": 0, "end_to_end_incorrect": 3,
        "failures": {"technical": 3}}), encoding="utf-8")

    listed = list_campaigns(tmp_path)
    indexed = index_campaign(tmp_path, "failed-campaign")

    assert listed[0]["campaign_id"] == "failed-campaign"
    assert listed[0]["order_count"] == 0
    assert indexed["orders"] == []
    assert indexed["report"]["failures"]["technical"] == 3
