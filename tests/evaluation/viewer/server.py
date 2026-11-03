"""Serve saved order diagnostics and a standalone browser UI."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

from evaluation.viewer_contract import ContractError, validate_order_diagnostic
from evaluation.viewer.summary import summarize_campaign, summarize_order
from evaluation.viewer.costs import order_costs, summarize_events, validate_rates


STATIC = Path(__file__).parent / "static"
MIME = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8",
        "style.css": "text/css; charset=utf-8"}


def _within(base: Path, relative: str) -> Path:
    candidate = (base / relative).resolve()
    if not candidate.is_relative_to(base.resolve()):
        raise ValueError("Path leaves artifacts directory")
    return candidate


def _read_diagnostic(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    validate_order_diagnostic(value)
    refs = {item["run_id"]: item["path"] for item in value["artifact_refs"]["results"]}
    public_fields = ("validator_type", "provider", "model", "config_version",
                     "temperature", "evidence_search_strategy")
    for validation in value["validations"]:
        metadata = validation.get("validator") or {}
        result_path = path.parent / refs.get(validation["run_id"], "")
        if result_path.is_file() and result_path.parent == path.parent:
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
                source = result.get("validator") or {}
                metadata = {field: metadata.get(field, source.get(field)) for field in public_fields}
            except (OSError, ValueError, TypeError):
                pass
        if metadata:
            validation["validator"] = metadata
        strategy = metadata.get("evidence_search_strategy")
        router = validation["stages"]["router"]
        router["observations"]["evidence_search_strategy"] = strategy
        if (strategy and strategy != "LOCAL" and router["execution_status"] == "NOT_RECORDED"
                and not router["observations"].get("sources")):
            router.update(execution_status="SKIPPED", assessment="SKIPPED",
                          missing_reason=f"La estrategia {strategy} obtiene evidencia sin usar Source Router.")
            router["observations"]["skip_reason"] = "EXTERNAL_EVIDENCE_STRATEGY"
    return validate_order_diagnostic(value)


def _issue_type(stage_name: str, stage: dict, check: dict) -> str:
    if check.get("type") in {"warning", "error"}:
        return check["type"]
    if stage_name == "generation" and check.get("code") not in {"GENERATION_ERROR", "MODULE_FAILED"}:
        return "warning"
    if stage_name == "router" and (stage.get("observations") or {}).get("sources"):
        return "warning"
    return "warning" if check.get("status") == "PARTIAL" else "error"


def _diagnostic_incidents(diagnostic: dict, file_name: str) -> list[dict]:
    """Flatten navigable findings without changing the saved diagnostic."""
    incidents = []

    def collect(stage_name, stage, *, assertion_id=None, run_id=None, validator_id=None):
        checks = [check for check in stage.get("checks", [])
                  if check.get("status") in {"FAIL", "PARTIAL"}]
        if not checks and stage.get("assessment") in {"FAIL", "PARTIAL"}:
            checks = [{"code": "MODULE_FAILED", "status": stage["assessment"],
                       "detail": stage.get("missing_reason") or "La causa no quedó registrada."}]
        for check in checks:
            incidents.append({"file": file_name,
                              "order_id": diagnostic["identity"]["order_id"],
                              "dataset_id": diagnostic["identity"]["dataset_id"],
                              "repetition": diagnostic["identity"]["repetition"],
                              "assertion_id": assertion_id, "run_id": run_id,
                              "validator_id": validator_id, "stage": stage_name,
                              "assessment": stage["assessment"],
                              "type": _issue_type(stage_name, stage, check),
                              "code": check.get("code", "MODULE_FAILED"),
                              "detail": check.get("detail", "")})

    collect("generation", diagnostic["order"]["generation"])
    for validation in diagnostic["validations"]:
        for stage_name, stage in validation["stages"].items():
            collect(stage_name, stage, assertion_id=validation["assertion_id"],
                    run_id=validation["run_id"], validator_id=validation["validator_id"])
    return incidents


def _saved_order_dates(directory: Path, diagnostic: dict) -> tuple[str | None, str | None]:
    """Read order timestamps when the referenced immutable artifact has them."""
    name = diagnostic.get("artifact_refs", {}).get("order")
    if not name:
        return None, None
    path = directory / name
    if not path.is_file() or path.parent != directory:
        return None, None
    try:
        order = json.loads(path.read_text(encoding="utf-8"))
        return order.get("created_at"), order.get("updated_at")
    except (OSError, ValueError, TypeError):
        return None, None


def _date_key(value: str | None) -> float:
    if not value:
        return float("-inf")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return float("-inf")


def _campaign_rates(directory: Path) -> dict:
    path = directory / "cost-rates.json"
    if not path.exists():
        return {"schema_version": "evaluation-cost-rates-v1", "currency": "USD", "llm": [], "search": []}
    if not path.is_file() or path.resolve().parent != directory.resolve():
        raise ValueError("cost-rates.json must be a regular file inside the campaign")
    return validate_rates(json.loads(path.read_text(encoding="utf-8")))


def index_campaign(root: Path, campaign: str) -> dict:
    directory = _within(root, campaign)
    if not directory.is_dir() or directory.parent != root.resolve():
        raise FileNotFoundError(campaign)
    manifest_path = directory / "manifest.json"
    report_path = directory / "report.json"
    manifest_error = None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    except (OSError, ValueError) as exc:
        manifest, manifest_error = {}, f"manifest.json: {type(exc).__name__}"
    report_error = None
    try:
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    except (OSError, ValueError) as exc:
        report, report_error = {}, f"report.json: {type(exc).__name__}"
    orders, errors, incidents, order_summaries, cost_events = [], [], [], [], []
    try:
        rates = _campaign_rates(directory)
    except (OSError, ValueError, TypeError) as exc:
        errors.append(f"cost-rates.json: {type(exc).__name__}: {exc}")
        rates = {"schema_version": "evaluation-cost-rates-v1", "currency": "USD", "llm": [], "search": []}
    if manifest_error:
        errors.append(manifest_error)
    if report_error:
        errors.append(report_error)
    for path in sorted(directory.glob("*-viewer.json")):
        try:
            diagnostic = _read_diagnostic(path)
            identity = diagnostic["identity"]
            if identity["campaign_id"] != campaign:
                raise ContractError("campaign_id does not match directory")
            order = diagnostic["order"]
            validations = diagnostic["validations"]
            summary = summarize_order(diagnostic)
            costs = order_costs(diagnostic, rates)
            order_summaries.append(summary)
            created_at, updated_at = _saved_order_dates(directory, diagnostic)
            order_incidents = _diagnostic_incidents(diagnostic, path.name)
            for incident in order_incidents:
                incident.update(created_at=created_at, updated_at=updated_at)
            incidents.extend(order_incidents)
            correct = sum(row["stages"]["llm"]["assessment"] == "PASS" for row in validations)
            warnings = sum(item["type"] == "warning" for item in order_incidents)
            technical_errors = sum(item["type"] == "error" for item in order_incidents)
            orders.append({"file": path.name, "order_id": identity["order_id"],
                           "dataset_id": identity["dataset_id"], "repetition": identity["repetition"],
                           "created_at": created_at, "updated_at": updated_at,
                           "status": order["status"], "assertions": len(order["assertions"]),
                           "validations": len(validations), "correct_validations": correct,
                           "warnings": warnings, "errors": technical_errors,
                           "findings": warnings + technical_errors, "summary": summary,
                           "costs": {key: value for key, value in costs.items() if key != "ledger"}})
            cost_events.extend(costs["ledger"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
    orders.sort(key=lambda item: _date_key(item.get("created_at")), reverse=True)
    incidents.sort(key=lambda item: _date_key(item.get("created_at")), reverse=True)
    return {"campaign_id": campaign, "status": manifest.get("status", "UNKNOWN"),
            "created_at": manifest.get("created_at"), "has_manifest": manifest_path.exists(),
            "orders": orders, "report": report,
            "summary": summarize_campaign(order_summaries),
            "costs": {**summarize_events(cost_events), "rates_version": rates["schema_version"],
                      "rates_configured": (directory / "cost-rates.json").exists()},
            "incidents": incidents, "errors": errors}


def list_campaigns(root: Path) -> list[dict]:
    if not root.is_dir():
        return []
    campaigns = []
    for path in sorted(root.iterdir(), reverse=True):
        if path.is_dir() and not path.is_symlink():
            try:
                summary = index_campaign(root, path.name)
                if summary["orders"] or summary["errors"] or summary["has_manifest"]:
                    campaigns.append({key: summary[key] for key in
                                      ("campaign_id", "status", "created_at", "errors")}
                                     | {"order_count": len(summary["orders"])})
            except (OSError, ValueError):
                continue
    campaigns.sort(key=lambda item: _date_key(item.get("created_at")), reverse=True)
    return campaigns


def make_handler(root: Path):
    root = root.resolve()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body, content_type="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            try:
                if path == "/api/campaigns":
                    return self._send(200, list_campaigns(root))
                parts = path.strip("/").split("/")
                if len(parts) >= 3 and parts[:2] == ["api", "campaigns"]:
                    campaign = parts[2]
                    directory = _within(root, campaign)
                    if directory.parent != root or not directory.is_dir():
                        raise FileNotFoundError(campaign)
                    if len(parts) == 4 and parts[3] == "orders":
                        return self._send(200, index_campaign(root, campaign))
                    if len(parts) == 5 and parts[3] == "orders":
                        name = parts[4]
                        if not name.endswith("-viewer.json"):
                            raise FileNotFoundError(name)
                        file = _within(directory, name)
                        if file.parent != directory:
                            raise FileNotFoundError(name)
                        diagnostic = _read_diagnostic(file)
                        if diagnostic["identity"]["campaign_id"] != campaign:
                            raise ContractError("campaign_id does not match directory")
                        rates = _campaign_rates(directory)
                        return self._send(200, diagnostic | {"viewer_summary": summarize_order(diagnostic),
                                                              "costs": order_costs(diagnostic, rates)})
                    if len(parts) == 5 and parts[3] == "artifacts":
                        name = parts[4]
                        file = _within(directory, name)
                        if file.parent != directory or file.suffix != ".json":
                            raise FileNotFoundError(name)
                        return self._send(200, json.loads(file.read_text(encoding="utf-8")))
                if path in ("/", "/index.html", "/app.js", "/style.css"):
                    name = "index.html" if path == "/" else path[1:]
                    return self._send(200, (STATIC / name).read_bytes(), MIME[name])
                raise FileNotFoundError(path)
            except FileNotFoundError:
                self._send(404, {"error": "not_found"})
            except (ContractError, ValueError, KeyError, TypeError) as exc:
                self._send(422, {"error": "invalid_artifact", "detail": str(exc)})
            except OSError as exc:
                self._send(500, {"error": "read_error", "detail": type(exc).__name__})

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description="Browse saved evaluation orders locally")
    parser.add_argument("--artifacts-root", type=Path, default=Path("tests/data/evaluation/artifacts"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.artifacts_root))
    print(f"Benchmark viewer: http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
