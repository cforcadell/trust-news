#!/usr/bin/env python3
"""Plan and maintain a dedicated Keycloak client for an API integration.

Dry-run is read-only. Apply requires an explicit Kubernetes context and the
SHA-256 of the current plan. Secrets are written only to private host files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from scripts.security.migrate_s03_owners import (
    keycloak_admin_token, mongo_uri, read_secret, start_port_forward,
    validate_apply_request,
)
from scripts.security.provision_s03_gui_user import issuer_and_realm, non_negative_int
from scripts.security.reconcile_s03_keycloak import (
    attach_audiences, confidential_service_client, request as keycloak_request,
)

ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{2,47}\Z")
MARKER = "trustnews_integration_id"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True)
    parser.add_argument("--integration-id", required=True)
    parser.add_argument("--operation", choices=("create", "limits", "rotate", "suspend", "reactivate", "retire"), default="create")
    parser.add_argument("--org-id")
    parser.add_argument("--expires-at", help="Future ISO 8601 timestamp with timezone")
    parser.add_argument("--action", action="append", default=[])
    parser.add_argument("--news-generation-limit", type=non_negative_int)
    parser.add_argument("--blockchain-validation-limit", type=non_negative_int)
    parser.add_argument("--org-news-generation-limit", type=non_negative_int)
    parser.add_argument("--org-blockchain-validation-limit", type=non_negative_int)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-context")
    parser.add_argument("--confirm-plan")
    return parser.parse_args()


def client_id_for(integration_id: str) -> str:
    integration_id = normalize_integration_id(integration_id)
    if not ID_PATTERN.fullmatch(integration_id):
        raise ValueError("Integration ID must be 3-48 lowercase letters, digits or hyphens")
    return f"tnapi-{integration_id}"


def normalize_integration_id(integration_id: str) -> str:
    """Accept a numeric TUI shorthand while keeping IDs app-owned and stable."""
    if integration_id.isdecimal() and int(integration_id) > 0:
        return f"integration-{int(integration_id):03d}"
    return integration_id


def parse_expiry(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed <= datetime.now(timezone.utc):
        raise ValueError("Expiry must be in the future and include a timezone")
    return parsed.astimezone(timezone.utc)


def catalog(root: Path) -> dict[str, set[str]]:
    rows = json.loads((root / "api/common/security/integration-routes.json").read_text())
    actions: dict[str, set[str]] = {}
    for row in rows:
        actions.setdefault(row["action"], set()).update(row["audiences"])
    return actions


def credential_path(root: Path, integration_id: str) -> Path:
    directory = root / "secrets" / "clients"
    for path in (directory.parent, directory):
        if path.is_symlink():
            raise RuntimeError("Private directory cannot be a symlink")
        path.mkdir(mode=0o700, exist_ok=True)
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise RuntimeError("Private directory must be owned by operator and mode 0700")
    return directory / f"api-{integration_id}.json"


def save_credentials(path: Path, client_id: str, secret: str, *, replace: bool) -> None:
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if not replace or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise RuntimeError("Existing credentials file cannot be replaced safely")
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"client_id": client_id, "client_secret": secret}, handle)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def plan_hash(plan: dict) -> str:
    return hashlib.sha256(json.dumps(plan, sort_keys=True, default=str,
                                     separators=(",", ":")).encode()).hexdigest()


def checked_state(args: argparse.Namespace, issuer: str, client_state: dict | None,
                  binding: dict | None, quota: dict | None) -> str:
    if args.operation == "create":
        if not any((client_state, binding, quota)):
            return "READY"
        if (not client_state or client_state.get("attributes", {}).get(MARKER) != args.integration_id
                or client_state.get("enabled") is not False
                or binding and binding.get("status") != "pending"):
            return "BLOCKED_EXISTING"
        if binding and (binding.get("issuer") != issuer or binding.get("azp") != client_id_for(args.integration_id)
                        or binding.get("org_id") != args.org_id
                        or sorted(binding.get("actions", [])) != sorted(set(args.action))
                        or (binding.get("expires_at") or datetime.min.replace(tzinfo=timezone.utc)).replace(
                            tzinfo=timezone.utc) != parse_expiry(args.expires_at)):
            return "BLOCKED_MISMATCH"
        if quota and (quota.get("quota_id") != f"integration_{args.integration_id}"
                      or quota.get("org_id") != args.org_id or quota.get("status") != "Active"
                      or quota.get("limits") != {"news_generation": args.news_generation_limit,
                                                 "blockchain_validation": args.blockchain_validation_limit}
                      or any(quota.get("consumed", {}).values())):
            return "BLOCKED_MISMATCH"
        return "RESUME"
    if not all((client_state, binding, quota)):
        return "BLOCKED_MISSING"
    if (client_state.get("attributes", {}).get(MARKER) != args.integration_id
            or binding.get("issuer") != issuer or binding.get("azp") != client_id_for(args.integration_id)
            or binding.get("quota_id") != f"integration_{args.integration_id}"
            or quota.get("quota_id") != binding.get("quota_id")):
        return "BLOCKED_MISMATCH"
    if args.operation in {"limits", "rotate", "suspend"} and quota.get("status") != "Active":
        return "BLOCKED_QUOTA"
    if args.operation in {"suspend", "retire"} and any(
        value > 0 for value in (quota.get("reserved") or {}).values()
    ):
        return "BLOCKED_PENDING_OPERATIONS"
    allowed = {
        "limits": {"active"},
        "rotate": {"active"}, "suspend": {"active"},
        "reactivate": {"suspended"}, "retire": {"active", "suspended"},
    }
    if binding.get("status") not in allowed[args.operation]:
        return "BLOCKED_STATE"
    expected_quota_status = {"active": "Active", "suspended": "Suspended", "retired": "Retired"}
    if quota.get("status") != expected_quota_status[binding["status"]]:
        return "BLOCKED_QUOTA"
    if client_state.get("enabled") is not (binding.get("status") == "active"):
        return "BLOCKED_KEYCLOAK_STATE"
    expiry = binding.get("expires_at")
    if isinstance(expiry, datetime):
        expiry = expiry.replace(tzinfo=expiry.tzinfo or timezone.utc)
    if args.operation == "reactivate" and (not isinstance(expiry, datetime) or expiry <= datetime.now(timezone.utc)):
        return "BLOCKED_EXPIRED"
    return "READY"


def main() -> int:
    args = parse_args()
    args.integration_id = normalize_integration_id(args.integration_id)
    validate_apply_request(apply=args.apply, context=args.context,
                           confirm_context=args.confirm_context, confirm_plan=args.confirm_plan)
    client_id = client_id_for(args.integration_id)
    quota_id = f"integration_{args.integration_id}"
    root_path = Path(__file__).resolve().parents[2]
    actions_catalog = catalog(root_path)
    if args.operation == "create":
        if (not args.org_id or not args.expires_at or not args.action
                or args.news_generation_limit is None or args.blockchain_validation_limit is None
                or args.org_news_generation_limit is None or args.org_blockchain_validation_limit is None):
            raise ValueError("Create requires organization, expiry, actions and integration/organization limits")
        UUID(args.org_id)
        actions = sorted(set(args.action))
        if set(actions) - set(actions_catalog):
            raise ValueError("Unknown integration action")
        expiry = parse_expiry(args.expires_at)
    elif args.operation == "limits":
        if (args.org_id or args.expires_at or args.action
                or any(value is None for value in (
                    args.news_generation_limit, args.blockchain_validation_limit,
                    args.org_news_generation_limit, args.org_blockchain_validation_limit))):
            raise ValueError("Limits operation requires both integration and organization limits")
        actions, expiry = [], None
    else:
        if (args.org_id or args.expires_at or args.action or args.news_generation_limit is not None
                or args.blockchain_validation_limit is not None
                or args.org_news_generation_limit is not None
                or args.org_blockchain_validation_limit is not None):
            raise ValueError("Maintenance operations cannot change creation fields")
        actions, expiry = [], None
    issuer, realm = issuer_and_realm(args.context)
    mongo_secret = read_secret(args.context, "mongodb-app-secret", "apis")
    keycloak_secret = read_secret(args.context, "keycloak-admin-secret", "infra")

    import httpx
    from pymongo import MongoClient

    with ExitStack() as stack:
        mongo_port = start_port_forward(stack, args.context, "infra", "mongodb", 27017)
        keycloak_port = start_port_forward(stack, args.context, "infra", "keycloak", 8080)
        with MongoClient(mongo_uri(mongo_secret, mongo_port), serverSelectionTimeoutMS=5000) as mongo:
            database = mongo[mongo_secret["MONGO_APP_DATABASE"]]
            database.command("ping")
            bindings = database["s03_integrations"]
            organizations = database["s03_organizations"]
            with httpx.Client(base_url=f"http://127.0.0.1:{keycloak_port}/auth", timeout=15) as client:
                token = keycloak_admin_token(client, keycloak_secret["ADMIN_USER"],
                                             keycloak_secret["ADMIN_PASSWORD"])
                client.headers["Authorization"] = f"Bearer {token}"
                kc_root = f"/admin/realms/{realm}"
                matches = [item for item in keycloak_request(
                    client, "GET", f"{kc_root}/clients", params={"clientId": client_id})
                    if item.get("clientId") == client_id]
                if len(matches) > 1:
                    raise RuntimeError("Duplicate Keycloak client")
                client_state = (keycloak_request(client, "GET", f"{kc_root}/clients/{matches[0]['id']}")
                                if matches else None)
                binding = bindings.find_one({"integration_id": args.integration_id}, {"_id": 0})
                org_state = organizations.find_one({"org_id": args.org_id if args.operation == "create"
                                                    else (binding or {}).get("org_id")}, {"_id": 0})
                quota = (org_state or {}).get("integrations", {}).get(args.integration_id)
                state = checked_state(args, issuer, client_state, binding, quota)
                scope_ids: list[str] = []
                if args.operation != "create" and client_state and binding:
                    required_names = {"trustnews-gateway-audience"} | {
                        f"s03-aud-{audience}" for action in binding.get("actions", [])
                        for audience in actions_catalog.get(action, set())
                    }
                    assigned = keycloak_request(client, "GET", f"{kc_root}/clients/{matches[0]['id']}/default-client-scopes")
                    assigned_names = {item.get("name") for item in assigned}
                    managed = {name for name in assigned_names if isinstance(name, str)
                               and (name.startswith("s03-aud-") or name == "trustnews-gateway-audience")}
                    if managed != required_names:
                        state = "BLOCKED_AUDIENCE"
                if args.operation == "create":
                    active_membership = database["s03_memberships"].find_one(
                        {"org_id": args.org_id, "active": True}, {"_id": 1})
                    # Existing organizations can be API-only and have no human
                    # membership. Legacy organizations are still initialized
                    # from an active membership when their S03 org record is absent.
                    if not org_state and not active_membership:
                        state = "BLOCKED_ORGANIZATION"
                    if org_state and org_state.get("status") != "active":
                        state = "BLOCKED_ORGANIZATION"
                    org_limits = {"news_generation": args.org_news_generation_limit,
                                  "blockchain_validation": args.org_blockchain_validation_limit}
                    if org_state and org_state.get("limits") != org_limits:
                        state = "BLOCKED_ORGANIZATION_LIMITS"
                    if any(plan_limit > org_limits[field] for field, plan_limit in {
                        "news_generation": args.news_generation_limit,
                        "blockchain_validation": args.blockchain_validation_limit,
                    }.items()):
                        state = "BLOCKED_ORGANIZATION_LIMITS"
                    scope_names = {"trustnews-gateway-audience"} | {
                        f"s03-aud-{audience}" for action in actions
                        for audience in actions_catalog[action]
                    }
                    scopes = keycloak_request(client, "GET", f"{kc_root}/client-scopes")
                    for name in sorted(scope_names):
                        found = [scope for scope in scopes if scope.get("name") == name]
                        if len(found) != 1:
                            state = "BLOCKED_AUDIENCE"
                        else:
                            scope_ids.append(found[0]["id"])
                    if client_state:
                        assigned = keycloak_request(
                            client, "GET", f"{kc_root}/clients/{matches[0]['id']}/default-client-scopes")
                        managed = {item.get("name") for item in assigned if isinstance(item.get("name"), str)
                                   and (item["name"].startswith("s03-aud-")
                                        or item["name"] == "trustnews-gateway-audience")}
                        if managed - scope_names:
                            state = "BLOCKED_AUDIENCE"
                    if (root_path / "secrets" / "clients" / f"api-{args.integration_id}.json").exists() and state == "READY":
                        state = "BLOCKED_CREDENTIALS"
                if args.operation == "limits" and org_state and quota:
                    proposed = {"news_generation": args.news_generation_limit,
                                "blockchain_validation": args.blockchain_validation_limit}
                    proposed_org = {"news_generation": args.org_news_generation_limit,
                                    "blockchain_validation": args.org_blockchain_validation_limit}
                    for field in proposed:
                        if (proposed[field] > proposed_org[field]
                                or proposed[field] < quota.get("consumed", {}).get(field, 0) + quota.get("reserved", {}).get(field, 0)
                                or proposed_org[field] < org_state.get("consumed", {}).get(field, 0) + org_state.get("reserved", {}).get(field, 0)):
                            state = "BLOCKED_CONSUMPTION"
                plan = {
                    "schema": 1, "context": args.context, "operation": args.operation,
                    "issuer": issuer, "integration_id": args.integration_id,
                    "client_id": client_id, "org_id": args.org_id if args.operation == "create" else (binding or {}).get("org_id"),
                    "quota_id": quota_id, "actions": actions if args.operation == "create" else (binding or {}).get("actions", []),
                    "expires_at": expiry.isoformat() if expiry else str((binding or {}).get("expires_at", "")),
                    "limits": ({"news_generation": args.news_generation_limit,
                                "blockchain_validation": args.blockchain_validation_limit}
                               if args.operation in {"create", "limits"} else (quota or {}).get("limits")),
                    "org_limits": ({"news_generation": args.org_news_generation_limit,
                                    "blockchain_validation": args.org_blockchain_validation_limit}
                                   if args.operation in {"create", "limits"} else (org_state or {}).get("limits")),
                    "state": state,
                }
                digest = plan_hash(plan)
                print(f"s03_integration_plan context={args.context} operation={args.operation} "
                      f"integration_id={args.integration_id} state={state} actions={len(plan['actions'])} "
                      f"plan_sha256={digest}")
                if plan["limits"] and plan["org_limits"]:
                    print(f"limits integration_news={plan['limits']['news_generation']} "
                          f"integration_blockchain={plan['limits']['blockchain_validation']} "
                          f"organization_news={plan['org_limits']['news_generation']} "
                          f"organization_blockchain={plan['org_limits']['blockchain_validation']}")
                if not args.apply:
                    return 0 if state in {"READY", "RESUME"} else 3
                if state not in {"READY", "RESUME"} or digest != args.confirm_plan:
                    raise RuntimeError("Live plan differs from reviewed plan")
                if args.operation == "create":
                    client_uuid, created = confidential_service_client(
                        client, kc_root, client_id, create_disabled=True,
                        attributes={MARKER: args.integration_id})
                    if created != (state == "READY"):
                        raise RuntimeError("Keycloak client changed after plan")
                    attach_audiences(client, kc_root, client_uuid, scope_ids)
                    subject = keycloak_request(client, "GET", f"{kc_root}/clients/{client_uuid}/service-account-user")["id"]
                    secret = keycloak_request(client, "GET", f"{kc_root}/clients/{client_uuid}/client-secret")["value"]
                    secret_path = credential_path(root_path, args.integration_id)
                    if secret_path.exists():
                        info = secret_path.lstat()
                        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                                or stat.S_IMODE(info.st_mode) != 0o600
                                or json.loads(secret_path.read_text()) != {"client_id": client_id, "client_secret": secret}):
                            raise RuntimeError("Stored integration credentials differ")
                    else:
                        save_credentials(secret_path, client_id, secret, replace=False)
                    if not org_state:
                        organizations.insert_one({
                            "org_id": args.org_id, "status": "active", "limits": plan["org_limits"],
                            "consumed": {"news_generation": 0, "blockchain_validation": 0},
                            "reserved": {"news_generation": 0, "blockchain_validation": 0},
                            "integrations": {}, "quota_operations": [],
                        })
                    if not quota:
                        entry = {"quota_id": quota_id, "org_id": args.org_id, "status": "Active",
                                 "limits": plan["limits"],
                                 "consumed": {"news_generation": 0, "blockchain_validation": 0},
                                 "reserved": {"news_generation": 0, "blockchain_validation": 0}}
                        updated = organizations.update_one(
                            {"org_id": args.org_id, "status": "active",
                             f"integrations.{args.integration_id}": {"$exists": False}},
                            {"$set": {f"integrations.{args.integration_id}": entry}})
                        if updated.matched_count != 1:
                            raise RuntimeError("Organization changed during provisioning")
                    if not binding:
                        bindings.insert_one({"integration_id": args.integration_id, "org_id": args.org_id,
                                             "issuer": issuer, "azp": client_id, "sub": subject,
                                             "keycloak_client_uuid": client_uuid, "quota_id": quota_id,
                                             "status": "pending", "expires_at": expiry, "actions": actions})
                    elif (binding.get("sub") != subject or binding.get("keycloak_client_uuid") != client_uuid
                          or binding.get("quota_id") != quota_id):
                        raise RuntimeError("Pending integration binding differs")
                    current = keycloak_request(client, "GET", f"{kc_root}/clients/{client_uuid}")
                    keycloak_request(client, "PUT", f"{kc_root}/clients/{client_uuid}",
                                     json={**current, "enabled": True})
                    if keycloak_request(client, "GET", f"{kc_root}/clients/{client_uuid}").get("enabled") is not True:
                        raise RuntimeError("Keycloak client did not become enabled")
                    activated = bindings.update_one(
                        {"integration_id": args.integration_id, "status": "pending", "sub": subject,
                         "quota_id": quota_id, "org_id": args.org_id}, {"$set": {"status": "active"}})
                    if activated.matched_count != 1:
                        raise RuntimeError("Integration binding could not be activated")
                else:
                    client_uuid = matches[0]["id"]
                    if args.operation == "limits":
                        updated = organizations.update_one(
                            {"org_id": binding["org_id"], "status": "active",
                             f"integrations.{args.integration_id}.quota_id": quota_id,
                             f"integrations.{args.integration_id}.status": "Active",
                             "$expr": {"$and": [
                                 {"$lte": [{"$add": [f"$consumed.{field}", f"$reserved.{field}"]},
                                           plan["org_limits"][field]]}
                                 for field in plan["org_limits"]
                             ] + [
                                 {"$lte": [{"$add": [f"$integrations.{args.integration_id}.consumed.{field}",
                                                   f"$integrations.{args.integration_id}.reserved.{field}"]},
                                           plan["limits"][field]]}
                                 for field in plan["limits"]
                             ]}},
                            {"$set": {"limits": plan["org_limits"],
                                      f"integrations.{args.integration_id}.limits": plan["limits"]}})
                        if updated.matched_count != 1:
                            raise RuntimeError("Organization quota changed during update")
                    elif args.operation == "rotate":
                        secret = keycloak_request(client, "POST", f"{kc_root}/clients/{client_uuid}/client-secret")["value"]
                        save_credentials(credential_path(root_path, args.integration_id), client_id, secret, replace=True)
                    else:
                        target = {"suspend": "suspended", "reactivate": "active", "retire": "retired"}[args.operation]
                        enabled = args.operation == "reactivate"
                        if not enabled:
                            bindings.update_one({"integration_id": args.integration_id}, {"$set": {"status": target}})
                        keycloak_request(client, "PUT", f"{kc_root}/clients/{client_uuid}",
                                         json={**client_state, "enabled": enabled})
                        if enabled:
                            bindings.update_one({"integration_id": args.integration_id}, {"$set": {"status": target}})
                        changed = organizations.update_one(
                            {"org_id": binding["org_id"],
                             f"integrations.{args.integration_id}.quota_id": quota_id},
                            {"$set": {f"integrations.{args.integration_id}.status":
                                      {"suspend": "Suspended", "reactivate": "Active",
                                       "retire": "Retired"}[args.operation]}})
                        if changed.matched_count != 1:
                            raise RuntimeError("Integration quota state could not be updated")
                print(f"s03_integration_provision=APPLIED operation={args.operation} "
                      f"integration_id={args.integration_id}")
                return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"s03_integration_provision=ERROR error_type={type(exc).__name__}; "
              "details suppressed; inspect Keycloak and MongoDB before retry", file=sys.stderr)
        raise SystemExit(1) from None
