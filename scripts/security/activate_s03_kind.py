#!/usr/bin/env python3
"""Attach S03 credentials, TLS listeners and policy configuration to kind.

This is a local-only reconciler. It checks the kubectl context before writes,
reads Kubernetes objects to preserve their current image tags, and never
prints credentials or private keys. Re-running it yields the same desired pod
spec. It intentionally does not touch preproduction overlays.
"""

from __future__ import annotations

import argparse
import json
import subprocess


def kubectl(*args, input_data=None):
    result = subprocess.run(["kubectl", *args], input=input_data, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace").strip())
    return result.stdout


def obj(*args):
    return json.loads(kubectl(*args, "-o", "json"))


def patch(kind, name, namespace, value):
    kubectl("patch", kind, name, "-n", namespace, "--type=strategic", "-p", json.dumps(value, separators=(",", ":")))
    print(f"patched={namespace}/{kind}/{name}")


def env(name, value):
    return {"name": name, "value": value}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="docs/security/s03-local-services.json")
    parser.add_argument("--apply-kind", action="store_true")
    parser.add_argument("--phase", choices=("infra", "apis", "edge", "all"), default="all")
    args = parser.parse_args()
    context = kubectl("config", "current-context").decode().strip()
    if not context.startswith("kind-"):
        raise SystemExit(f"Refusing non-kind context: {context}")
    with open(args.config, encoding="utf-8") as handle:
        rows = json.load(handle)
    gateway_config = obj("get", "configmap", "gateway-config", "-n", "apis")["data"]
    issuer = gateway_config["KEYCLOAK_ISSUER_URL"]
    realm = issuer.rstrip("/").rsplit("/", 1)[-1]
    keycloak_origin = "https://keycloak.infra.svc.cluster.local:9443"
    token_url = f"{keycloak_origin}/auth/realms/{realm}/protocol/openid-connect/token"
    jwks_url = f"{keycloak_origin}/auth/realms/{realm}/protocol/openid-connect/certs"
    url = lambda name: f"https://{name}.apis.svc.cluster.local:9443"
    audience_map = {url(row["service"]): row["client"] for row in rows if row.get("client")}
    legacy_tls_origins = {
        f"http://{row['service']}.apis.svc.cluster.local:{row['http_port']}": url(row["service"])
        for row in rows if row["namespace"] == "apis"
    }
    gateway_image = obj("get", "deployment", "gateway", "-n", "apis")["spec"]["template"]["spec"]["containers"][0]["image"]
    app_env = {
        "gateway": {"NEWS_HANDLER_URL": url("news-handler"), "ADMIN_URL": url("admin-service"),
                    "GENERATE_ASSERTIONS_URL": url("generate-asertions")},
        "admin-service": {
            "NEWS_HANDLER_URL": url("news-handler"), "GENERATE_ASSERTIONS_URL": url("generate-asertions"),
            "SOURCE_ROUTER_URL": url("source-router"), "S03_TARGET_AUDIENCES": json.dumps(audience_map, separators=(",", ":")),
            "S03_TLS_ORIGINS": json.dumps(legacy_tls_origins, separators=(",", ":")),
        },
        "news-handler": {"ADMIN_URL": url("admin-service")},
        "generate-asertions": {"ADMIN_URL": url("admin-service")},
        "source-router": {"ADMIN_URL": url("admin-service")},
        "evidence-search": {},
        "validate-service-1": {"ADMIN_URL": url("admin-service")},
        "validate-service-2": {"ADMIN_URL": url("admin-service")},
        "validate-service-3": {"ADMIN_URL": url("admin-service")},
    }
    if not args.apply_kind:
        print(f"s03_kind_plan=PASS context={context} services={len(rows)} issuer={issuer}")
        return
    selected = [row for row in rows if args.phase == "all" or
                (args.phase == "infra" and row["namespace"] == "infra") or
                (args.phase == "apis" and row["namespace"] == "apis" and row["service"] != "gateway") or
                (args.phase == "edge" and row["service"] == "gateway")]
    for row in selected:
        namespace, service, deployment = row["namespace"], row["service"], row["deployment"]
        deployment_obj = obj("get", "deployment", deployment, "-n", namespace)
        containers = deployment_obj["spec"]["template"]["spec"]["containers"]
        app_container = next(c for c in containers if c["name"] == row["container"])
        image = gateway_image if namespace == "infra" else app_container["image"]
        proxy = {
            "name": "s03-tls-proxy", "image": image, "imagePullPolicy": "IfNotPresent",
            "command": ["python", "-m", "common.security.tls_proxy"],
            "env": [env("S03_PROXY_TARGET_PORT", str(row["http_port"])),
                    env("S03_TLS_CERT_FILE", "/etc/s03-tls/tls.crt"), env("S03_TLS_KEY_FILE", "/etc/s03-tls/tls.key")],
            "ports": [{"name": "s03-https", "containerPort": 9443}],
            "volumeMounts": [{"name": "s03-tls", "mountPath": "/etc/s03-tls", "readOnly": True}],
            "resources": {"requests": {"cpu": "10m", "memory": "32Mi"}, "limits": {"cpu": "200m", "memory": "128Mi"}},
        }
        patch_containers = [proxy]
        if client_id := row.get("client"):
            values = {
                "S03_ENABLED": "true", "S03_AUDIENCE": client_id,
                "KEYCLOAK_ISSUER_URL": issuer, "KEYCLOAK_JWKS_URL": jwks_url,
                "S03_TOKEN_URL": token_url, "S03_USER_CLIENTS": "TrustNewsWeb,TrustNewsApi",
                "S03_CA_FILE": "/etc/s03-ca/ca.crt",
            }
            if service == "generate-asertions":
                values["S03_POLICY_FILE"] = "/app/generate-asertions/s03-policy.json"
            elif service == "source-router":
                values["S03_POLICY_FILE"] = "/app/source-router/s03-policy.json"
            elif service == "evidence-search":
                values["S03_POLICY_FILE"] = "/app/evidence-search/s03-policy.json"
            elif service == "admin-service":
                values["S03_POLICY_FILE"] = "/app/admin/s03-policy.json"
            elif service == "news-handler":
                values["S03_POLICY_FILE"] = "/app/news-handler/s03-policy.json"
            else:
                values["S03_POLICY_FILE"] = "/app/common/security/runtime-policy.json"
            values.update(app_env.get(service, {}))
            if service.startswith("validate-service-"):
                values["SOURCE_ROUTER_URL"] = url("source-router")
                values["EVIDENCE_SEARCH_URL"] = url("evidence-search")
            env_from = list(app_container.get("envFrom", []))
            secret_name = row.get("secret_name", f"s03-client-{client_id}")
            secret_ref = {"secretRef": {"name": secret_name}}
            if secret_ref not in env_from:
                env_from.append(secret_ref)
            patch_containers.append({
                "name": row["container"],
                "envFrom": env_from,
                "env": [env(name, value) for name, value in values.items()],
                "volumeMounts": [{"name": "s03-ca", "mountPath": "/etc/s03-ca", "readOnly": True}],
            })
        deployment_patch = {"spec": {"template": {"spec": {
            "containers": patch_containers,
            "volumes": [{"name": "s03-tls", "secret": {"secretName": f"s03-tls-{service}"}},
                        {"name": "s03-ca", "secret": {"secretName": "s03-internal-ca"}}],
        }}}}
        patch("deployment", deployment, namespace, deployment_patch)
        current_ports = obj("get", "service", service, "-n", namespace)["spec"]["ports"]
        ports = []
        for port in current_ports:
            if port["port"] == 9443:
                continue
            preserved = {key: port[key] for key in ("name", "port", "targetPort", "protocol", "appProtocol", "nodePort") if key in port}
            preserved["name"] = preserved.get("name") or "http"
            ports.append(preserved)
        ports.append({"name": "s03-https", "port": 9443, "targetPort": 9443, "protocol": "TCP"})
        kubectl("patch", "service", service, "-n", namespace, "--type=merge", "-p", json.dumps({"spec": {"ports": ports}}, separators=(",", ":")))
        print(f"patched={namespace}/service/{service}")

    if args.phase not in ("edge", "all"):
        print(f"s03_kind_activation=APPLIED phase={args.phase} services={len(selected)}")
        return
    transport = {"apiVersion": "traefik.io/v1alpha1", "kind": "ServersTransport",
                 "metadata": {"name": "s03-gateway", "namespace": "apis"},
                 "spec": {"serverName": "gateway.apis.svc.cluster.local", "rootCAs": [{"secret": "s03-internal-ca"}]}}
    kubectl("apply", "-f", "-", input_data=json.dumps(transport).encode())
    # Traefik reads upstream transport annotations from the Kubernetes Service.
    patch("service", "gateway", "apis", {"metadata": {"annotations": {
        "traefik.ingress.kubernetes.io/service.serversscheme": "https",
        "traefik.ingress.kubernetes.io/service.serverstransport": "apis-s03-gateway@kubernetescrd",
    }}})
    ingress_rules = obj("get", "ingress", "gateway-ingress", "-n", "apis")["spec"]["rules"]
    for rule in ingress_rules:
        for route in rule["http"]["paths"]:
            if route["backend"]["service"]["name"] == "gateway":
                route["backend"]["service"]["port"] = {"number": 9443}
    patch("ingress", "gateway-ingress", "apis", {"spec": {"rules": ingress_rules}})
    print(f"s03_kind_activation=APPLIED context={context} phase={args.phase} services={len(selected)}")


if __name__ == "__main__":
    main()
