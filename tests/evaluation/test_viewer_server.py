"""The viewer reads saved diagnostics without modifying campaign artifacts."""

import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import urlopen
from http.server import ThreadingHTTPServer

from evaluation.viewer.server import index_campaign, list_campaigns, make_handler


FIXTURE = Path(__file__).resolve().parents[1] / "data/evaluation/resources/viewer-fixtures/order-diagnostic-v1.json"


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
    assert len(indexed["errors"]) == 1
    assert list_campaigns(tmp_path)[0]["order_count"] == 1


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
