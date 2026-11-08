#!/usr/bin/env python3
"""Idempotently provision configured audiences and service accounts in Keycloak.

Use with a localhost-only port-forward to local Keycloak or with an explicitly
configured preproduction endpoint. Admin credentials come from environment;
generated service secrets go to private files and are never printed. Local
overlay output is ignored by Git. This script does not assign human roles.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
from pathlib import Path

import httpx


def exact_one(rows, name, field="clientId"):
    matches = [row for row in rows if row.get(field) == name]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one {name}; found {len(matches)}")
    return matches[0]


def request(client, method, path, **kwargs):
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else None


def reconcile(config, client, token, credential_paths):
    realm = config["realm"]
    root = f"/admin/realms/{realm}"
    client.headers["Authorization"] = f"Bearer {token}"
    existing_user_clients = {}
    for client_id in config["user_clients"]:
        existing_user_clients[client_id] = exact_one(request(client, "GET", f"{root}/clients", params={"clientId": client_id}), client_id)

    all_audiences = set(config["user_audiences"])
    for audiences in config["service_clients"].values():
        all_audiences.update(audiences)
    scopes = {}
    for audience in sorted(all_audiences):
        name = f"s03-aud-{audience}"
        rows = request(client, "GET", f"{root}/client-scopes")
        matches = [row for row in rows if row.get("name") == name]
        if len(matches) > 1:
            raise RuntimeError(f"Duplicate client scope {name}")
        if not matches:
            request(client, "POST", f"{root}/client-scopes", json={"name": name, "protocol": "openid-connect"})
            rows = request(client, "GET", f"{root}/client-scopes")
        scope = exact_one(rows, name, "name")
        scope_id = scope["id"]
        mappers = request(client, "GET", f"{root}/client-scopes/{scope_id}/protocol-mappers/models")
        mapper = [row for row in mappers if row.get("name") == name]
        if len(mapper) > 1:
            raise RuntimeError(f"Duplicate audience mapper {name}")
        desired = {"name": name, "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper",
                   "config": {"included.custom.audience": audience, "access.token.claim": "true", "id.token.claim": "false"}}
        if mapper:
            observed = mapper[0]
            if observed.get("protocolMapper") != desired["protocolMapper"] or any(observed.get("config", {}).get(k) != v for k, v in desired["config"].items()):
                raise RuntimeError(f"Existing mapper differs: {name}")
        else:
            request(client, "POST", f"{root}/client-scopes/{scope_id}/protocol-mappers/models", json=desired)
        scopes[audience] = scope_id

    def attach(client_id, audiences):
        row = exact_one(request(client, "GET", f"{root}/clients", params={"clientId": client_id}), client_id)
        client_uuid = row["id"]
        assigned = {item["id"] for item in request(client, "GET", f"{root}/clients/{client_uuid}/default-client-scopes")}
        for audience in audiences:
            scope_id = scopes[audience]
            if scope_id not in assigned:
                request(client, "PUT", f"{root}/clients/{client_uuid}/default-client-scopes/{scope_id}")
        return client_uuid

    for client_id in existing_user_clients:
        attach(client_id, config["user_audiences"])

    for client_id, audiences in config["service_clients"].items():
        rows = request(client, "GET", f"{root}/clients", params={"clientId": client_id})
        matches = [row for row in rows if row.get("clientId") == client_id]
        if len(matches) > 1:
            raise RuntimeError(f"Duplicate client {client_id}")
        if not matches:
            request(client, "POST", f"{root}/clients", json={
                "clientId": client_id, "enabled": True, "protocol": "openid-connect", "publicClient": False,
                "serviceAccountsEnabled": True, "standardFlowEnabled": False, "directAccessGrantsEnabled": False,
            })
        client_uuid = attach(client_id, audiences)
        state = request(client, "GET", f"{root}/clients/{client_uuid}")
        if state.get("publicClient") or not state.get("serviceAccountsEnabled") or state.get("standardFlowEnabled"):
            raise RuntimeError(f"Service client has unsafe flows: {client_id}")
        secret = request(client, "GET", f"{root}/clients/{client_uuid}/client-secret").get("value")
        if not secret:
            raise RuntimeError(f"Missing service secret: {client_id}")
        path = credential_paths[client_id]
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"S03_CLIENT_ID={client_id}\nS03_CLIENT_SECRET={secret}\n")
        print(f"service_client={client_id} audiences={len(audiences)} secret_file={path}")

    for role in config.get("roles", []):
        response = client.get(f"{root}/roles/{role}")
        if response.status_code == 404:
            request(client, "POST", f"{root}/roles", json={"name": role})
        else:
            response.raise_for_status()
    print(f"s03_keycloak_reconciliation=PASS realm={realm} roles_unassigned={len(config.get('roles', []))}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="docs/security/s03-keycloak-clients.json")
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--output-dir", help="Private directory outside the repository")
    destination.add_argument("--local-overlays", action="store_true",
                             help="Write each service credential to its ignored local API overlay file")
    parser.add_argument("--services-config", default="docs/security/s03-local-services.json",
                        help="Service inventory used to map clients to local overlays")
    parser.add_argument("--kind-local", action="store_true", help="Read local kind admin credentials from its Kubernetes Secret")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    if args.local_overlays and not args.kind_local:
        raise SystemExit("--local-overlays is restricted to credentials read from the local Kind Keycloak")
    if args.kind_local:
        context = subprocess.check_output(["kubectl", "config", "current-context"], text=True).strip()
        if not context.startswith("kind-"):
            raise SystemExit(f"Refusing local Keycloak credentials outside a kind context: {context}")
    if args.local_overlays:
        services_path = Path(args.services_config)
        if not services_path.is_absolute():
            services_path = root / services_path
        with services_path.open(encoding="utf-8") as handle:
            services = json.load(handle)
        credential_paths = {}
        for service in services:
            client_id = service.get("client")
            relative_path = service.get("local_credentials_file")
            if not client_id or not relative_path:
                continue
            path = (root / relative_path).resolve()
            if not path.is_relative_to(root / "k8s" / "apis"):
                raise SystemExit(f"Local credential path must stay under k8s/apis: {relative_path}")
            previous = credential_paths.get(client_id)
            if previous and previous != path:
                raise SystemExit(f"Conflicting local credential paths for {client_id}")
            credential_paths[client_id] = path
    else:
        output_dir = Path(args.output_dir).resolve()
        if output_dir.is_relative_to(root):
            raise SystemExit("Output directory must be outside the repository")
        output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(output_dir, 0o700)
        with open(args.config, encoding="utf-8") as handle:
            clients = json.load(handle)["service_clients"]
        credential_paths = {client_id: output_dir / f"{client_id}.env" for client_id in clients}
    if args.kind_local:
        raw = subprocess.check_output(["kubectl", "get", "secret", "keycloak-admin-secret", "-n", "infra", "-o", "json"])
        secret_data = json.loads(raw)["data"]
        username = base64.b64decode(secret_data["ADMIN_USER"]).decode()
        password = base64.b64decode(secret_data["ADMIN_PASSWORD"]).decode()
    else:
        username = os.environ["KC_ADMIN_USER"]
        password = os.environ["KC_ADMIN_PASSWORD"]
    base = os.environ.get("KC_ADMIN_URL", "http://127.0.0.1:18080/auth").rstrip("/")
    with open(args.config, encoding="utf-8") as handle:
        config = json.load(handle)
    missing_paths = set(config["service_clients"]) - set(credential_paths)
    if missing_paths:
        raise SystemExit(f"No credential destination configured for clients: {', '.join(sorted(missing_paths))}")
    with httpx.Client(base_url=base, timeout=15) as client:
        token = request(client, "POST", "/realms/master/protocol/openid-connect/token", data={
            "grant_type": "password", "client_id": "admin-cli", "username": username, "password": password,
        })["access_token"]
        reconcile(config, client, token, credential_paths)


if __name__ == "__main__":
    main()
