#!/usr/bin/env python3
"""Render the shared S03 Kubernetes runtime patches from the service inventory.

The generated files contain only non-secret pod and Service configuration.
Kustomize consumes them in both kind and K3s overlays.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "docs/security/s03-local-services.json"
OUTPUT = ROOT / "k8s/s03/runtime/patches"


def service_url(service: str) -> str:
    return f"https://{service}.apis.svc.cluster.local:9443"


def environment(row: dict, audiences: dict[str, str], tls_origins: dict[str, str]) -> dict[str, str]:
    values = {
        "S03_AUDIENCE": row["client"],
        "S03_POLICY_FILE": row["policy_file"],
    }
    for name, expression in row.get("runtime_env", {}).items():
        if expression.startswith("@service:"):
            values[name] = service_url(expression.removeprefix("@service:"))
        elif expression == "@audience-map":
            values[name] = json.dumps(audiences, separators=(",", ":"))
        elif expression == "@tls-origins":
            values[name] = json.dumps(tls_origins, separators=(",", ":"))
        else:
            raise ValueError(f"Unknown S03 runtime expression: {expression}")
    return values


def deployment_patch(row: dict, audiences: dict[str, str], tls_origins: dict[str, str]) -> dict:
    service = row["service"]
    proxy = {
        "name": "s03-tls-proxy",
        "image": "gateway",
        "imagePullPolicy": "IfNotPresent",
        "command": ["python", "-m", "common.security.tls_proxy"],
        "env": [
            {"name": "S03_PROXY_TARGET_PORT", "value": str(row["http_port"])},
            {"name": "S03_TLS_CERT_FILE", "value": "/etc/s03-tls/tls.crt"},
            {"name": "S03_TLS_KEY_FILE", "value": "/etc/s03-tls/tls.key"},
        ],
        "ports": [{"name": "s03-https", "containerPort": 9443}],
        "volumeMounts": [{"name": "s03-tls", "mountPath": "/etc/s03-tls", "readOnly": True}],
        "resources": {
            "requests": {"cpu": "10m", "memory": "32Mi"},
            "limits": {"cpu": "200m", "memory": "128Mi"},
        },
    }
    containers = [proxy]
    volumes = [{"name": "s03-tls", "secret": {"secretName": f"s03-tls-{service}"}}]
    if row.get("client"):
        containers.append({
            "name": row["container"],
            "env": [{"name": name, "value": value} for name, value in
                    environment(row, audiences, tls_origins).items()],
            "volumeMounts": [{"name": "s03-ca", "mountPath": "/etc/s03-ca", "readOnly": True}],
        })
        volumes.append({"name": "s03-ca", "secret": {"secretName": "s03-internal-ca"}})
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": row.get("patch_deployment", row["deployment"]),
                     "namespace": row["namespace"]},
        "spec": {"template": {"spec": {"containers": containers, "volumes": volumes}}},
    }


def service_patch(row: dict) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": row.get("patch_service", row["service"]), "namespace": row["namespace"]},
        "spec": {"ports": [{"name": "s03-https", "port": 9443, "targetPort": 9443, "protocol": "TCP"}]},
    }


def render() -> dict[Path, str]:
    rows = json.loads(INVENTORY.read_text(encoding="utf-8"))
    audiences = {service_url(row["service"]): row["client"] for row in rows if row.get("client")}
    tls_origins = {
        f"http://{row['service']}.apis.svc.cluster.local:{row['http_port']}": service_url(row["service"])
        for row in rows if row["namespace"] == "apis"
    }
    files = {}
    for row in rows:
        stem = f"{row['namespace']}-{row['service']}"
        files[OUTPUT / f"{stem}-deployment.json"] = json.dumps(
            deployment_patch(row, audiences, tls_origins), indent=2, ensure_ascii=False) + "\n"
        files[OUTPUT / f"{stem}-service.json"] = json.dumps(
            service_patch(row), indent=2, ensure_ascii=False) + "\n"
    return files


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail if checked-in patches differ from the inventory")
    args = parser.parse_args()
    files = render()
    if args.check:
        stale = [str(path.relative_to(ROOT)) for path, content in files.items()
                 if not path.exists() or path.read_text(encoding="utf-8") != content]
        stale.extend(str(path.relative_to(ROOT)) for path in OUTPUT.glob("*.json") if path not in files)
        if stale:
            raise SystemExit("S03 runtime patches out of date: " + ", ".join(stale))
    else:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        for path, content in files.items():
            path.write_text(content, encoding="utf-8")
    print(f"s03_runtime_patches={'CURRENT' if args.check else 'WRITTEN'} count={len(files)}")


if __name__ == "__main__":
    main()
