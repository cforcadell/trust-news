"""Serve saved order diagnostics and a standalone browser UI."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

from evaluation.viewer_contract import ContractError, validate_order_diagnostic


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
    return validate_order_diagnostic(value)


def index_campaign(root: Path, campaign: str) -> dict:
    directory = _within(root, campaign)
    if not directory.is_dir() or directory.parent != root.resolve():
        raise FileNotFoundError(campaign)
    manifest_path = directory / "manifest.json"
    manifest_error = None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    except (OSError, ValueError) as exc:
        manifest, manifest_error = {}, f"manifest.json: {type(exc).__name__}"
    orders, errors = [], []
    if manifest_error:
        errors.append(manifest_error)
    for path in sorted(directory.glob("*-viewer.json")):
        try:
            diagnostic = _read_diagnostic(path)
            identity = diagnostic["identity"]
            if identity["campaign_id"] != campaign:
                raise ContractError("campaign_id does not match directory")
            order = diagnostic["order"]
            validations = diagnostic["validations"]
            orders.append({"file": path.name, "order_id": identity["order_id"],
                           "dataset_id": identity["dataset_id"], "repetition": identity["repetition"],
                           "status": order["status"], "assertions": len(order["assertions"]),
                           "validations": len(validations),
                           "findings": sum(1 for row in validations for stage in row["stages"].values()
                                           for check in stage["checks"] if check["status"] == "FAIL")})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
    return {"campaign_id": campaign, "status": manifest.get("status", "UNKNOWN"),
            "created_at": manifest.get("created_at"), "orders": orders, "errors": errors}


def list_campaigns(root: Path) -> list[dict]:
    if not root.is_dir():
        return []
    campaigns = []
    for path in sorted(root.iterdir(), reverse=True):
        if path.is_dir() and not path.is_symlink():
            try:
                summary = index_campaign(root, path.name)
                if summary["orders"] or summary["errors"]:
                    campaigns.append({key: summary[key] for key in
                                      ("campaign_id", "status", "created_at", "errors")}
                                     | {"order_count": len(summary["orders"])})
            except (OSError, ValueError):
                continue
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
                        return self._send(200, diagnostic)
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
