#!/usr/bin/env python3
"""Plan or apply verified S03 memberships for exact legacy owner keys.

The default mode is read-only. Applying requires the explicitly selected
Kubernetes context, the hash printed by a reviewed plan, and a repeated target
context. Existing records are never rewritten; ambiguous or conflicting keys
block the whole apply.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from contextlib import ExitStack
from urllib.parse import quote_plus

CONFIG_DEFAULT = "docs/security/s03-owner-migration.json"
PLAN_SCHEMA_VERSION = 1


def kubectl(context: str, *args: str) -> dict:
    result = subprocess.run(
        ["kubectl", "--context", context, "--request-timeout=15s", *args],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"kubectl {' '.join(args[:3])} failed (exit {result.returncode})")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("kubectl returned invalid JSON") from exc


def read_secret(context: str, name: str, namespace: str) -> dict[str, str]:
    secret = kubectl(context, "get", "secret", name, "-n", namespace, "-o", "json")
    encoded = secret.get("data") or {}
    try:
        return {key: base64.b64decode(value, validate=True).decode("utf-8")
                for key, value in encoded.items()}
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"Secret {namespace}/{name} has invalid encoded data") from exc


def mongo_uri(secret: dict[str, str], port: int) -> str:
    database = secret["MONGO_APP_DATABASE"]
    user = quote_plus(secret["MONGO_APP_USER"])
    password = quote_plus(secret["MONGO_APP_PWD"])
    auth_source = quote_plus(secret["MONGO_APP_AUTHSOURCE"])
    return (f"mongodb://{user}:{password}@127.0.0.1:{port}/"
            f"{quote_plus(database)}?authSource={auth_source}")


def free_loopback_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def start_port_forward(stack: ExitStack, context: str, namespace: str,
                       service: str, remote_port: int) -> int:
    local_port = free_loopback_port()
    process = subprocess.Popen(
        ["kubectl", "--context", context, "-n", namespace, "port-forward",
         "--address", "127.0.0.1", f"service/{service}", f"{local_port}:{remote_port}"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    def stop() -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)

    stack.callback(stop)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"port-forward to {namespace}/{service} did not start")
        try:
            with socket.create_connection(("127.0.0.1", local_port), timeout=0.25):
                return local_port
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"port-forward to {namespace}/{service} timed out")


def keycloak_users(client, issuer: str, username: str, password: str) -> list[dict]:
    import httpx

    try:
        token = keycloak_admin_token(client, username, password)
        realm = issuer.rstrip("/").rsplit("/", 1)[-1]
        client.headers["Authorization"] = f"Bearer {token}"
        users: list[dict] = []
        offset = 0
        while True:
            response = client.get(f"/admin/realms/{realm}/users",
                                  params={"first": offset, "max": 100})
            response.raise_for_status()
            batch = response.json()
            users.extend(batch)
            if len(batch) < 100:
                break
            offset += 100
        return [row for row in users if row.get("enabled") and row.get("id") and row.get("username")
                and not row["username"].startswith("service-account-")]
    except (httpx.HTTPError, KeyError, ValueError):
        raise RuntimeError("Keycloak user inventory failed") from None
    finally:
        client.headers.pop("Authorization", None)


def keycloak_admin_token(client, username: str, password: str) -> str:
    response = client.post("/realms/master/protocol/openid-connect/token", data={
        "grant_type": "password", "client_id": "admin-cli",
        "username": username, "password": password,
    })
    response.raise_for_status()
    return response.json()["access_token"]


def build_plan(*, issuer: str, config: dict, order_counts: dict[str, int],
               quota_counts: dict[str, int], users: list[dict],
               memberships: list[dict]) -> dict:
    prefixes = config["legacy_prefixes"]
    existing = set(order_counts) | set(quota_counts)
    candidates: dict[str, set[str]] = {}
    enabled_users = []
    seen_subjects = set()
    for user in users:
        subject = user.get("id")
        if not subject or subject in seen_subjects:
            continue
        seen_subjects.add(subject)
        username = user.get("username") or "(username unavailable)"
        enabled_users.append({"subject": subject, "username": username})
        for prefix in prefixes:
            alias = f"{prefix}_{subject}"
            if alias in existing:
                candidates.setdefault(alias, set()).add(subject)

    ambiguous = {alias for alias, owners in candidates.items() if len(owners) != 1}
    aliases_by_subject: dict[str, list[str]] = {}
    for alias, owners in candidates.items():
        if alias not in ambiguous:
            aliases_by_subject.setdefault(next(iter(owners)), []).append(alias)
    username_by_subject = {row["subject"]: row["username"] for row in enabled_users}
    plan_rows = []
    for subject, aliases in sorted(aliases_by_subject.items()):
        org_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{issuer}|{subject}"))
        plan_rows.append({
            "issuer": issuer,
            "subject": subject,
            "org_id": org_id,
            "username": username_by_subject[subject],
            "aliases": [{
                "key": alias,
                "prefix": next(prefix for prefix in prefixes if alias == f"{prefix}_{subject}"),
                "orders": order_counts.get(alias, 0),
                "quotas": quota_counts.get(alias, 0),
            } for alias in sorted(aliases)],
        })

    alias_owner = {
        alias["key"]: (row["issuer"], row["subject"], row["org_id"])
        for row in plan_rows for alias in row["aliases"]
    }
    aliases_by_identity: dict[tuple[str, str, str], set[str]] = {}
    for row in plan_rows:
        identity = (row["issuer"], row["subject"], row["org_id"])
        aliases_by_identity[identity] = {alias["key"] for alias in row["aliases"]}
    conflicts = set(ambiguous)
    inactive_memberships = set()
    for membership in memberships:
        identity = (membership.get("issuer"), membership.get("subject"), membership.get("org_id"))
        if identity in aliases_by_identity and membership.get("active") is not True:
            inactive_memberships.update(aliases_by_identity[identity])
        for alias in membership.get("legacy_client_ids", []):
            expected = alias_owner.get(alias)
            if expected is None:
                continue
            if identity != expected:
                conflicts.add(alias)
            elif membership.get("active") is not True:
                inactive_memberships.add(alias)
    conflicts.update(inactive_memberships)

    mapped = set(alias_owner) - conflicts
    report = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "issuer": issuer,
        "users_considered": len(enabled_users),
        "mapped_users": len(plan_rows),
        "mapped_aliases": len(mapped),
        "unmapped_legacy_keys": len(existing - mapped),
        "unmapped_order_keys": len(set(order_counts) - mapped),
        "unmapped_quota_keys": len(set(quota_counts) - mapped),
        "ambiguous_or_conflicting_keys": len(conflicts),
        "plans": plan_rows,
    }
    fingerprint_payload = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    report["plan_sha256"] = hashlib.sha256(fingerprint_payload).hexdigest()
    report["can_apply"] = bool(plan_rows) and not conflicts
    return report


def print_plan(report: dict, context: str) -> None:
    print(f"s03_owner_plan context={context} issuer={report['issuer']}")
    print(" ".join(f"{key}={report[key]}" for key in (
        "users_considered", "mapped_users", "mapped_aliases", "unmapped_legacy_keys",
        "unmapped_order_keys", "unmapped_quota_keys", "ambiguous_or_conflicting_keys",
    )))
    for row in report["plans"]:
        orders = sum(alias["orders"] for alias in row["aliases"])
        quotas = sum(alias["quotas"] for alias in row["aliases"])
        prefixes = sorted({alias["prefix"] for alias in row["aliases"]})
        username = json.dumps(row["username"], ensure_ascii=True)
        print(f"owner username={username} aliases={len(row['aliases'])} "
              f"legacy_prefixes={','.join(prefixes)} orders={orders} quotas={quotas}")
    print(f"plan_sha256={report['plan_sha256']}")
    if report["ambiguous_or_conflicting_keys"]:
        state = "BLOCKED"
    elif not report["plans"]:
        state = "NO_MAPPINGS"
    else:
        state = "DRY_RUN"
    print(f"s03_owner_migration={state}")


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True, help="Explicit Kubernetes context")
    parser.add_argument("--config", default=CONFIG_DEFAULT, help="Legacy-key mapping configuration")
    parser.add_argument("--apply", action="store_true", help="Apply the reviewed plan")
    parser.add_argument("--confirm-context", help="Repeat the exact target context for apply")
    parser.add_argument("--confirm-plan", help="SHA-256 printed by the reviewed dry-run")
    return parser


def validate_apply_request(*, apply: bool, context: str, confirm_context: str | None,
                           confirm_plan: str | None) -> None:
    if apply:
        if confirm_context != context or not confirm_plan:
            raise SystemExit("Apply requires --confirm-context matching --context and --confirm-plan")
    elif confirm_context or confirm_plan:
        raise SystemExit("Confirmation flags are only valid together with --apply")


def main() -> int:
    args = build_cli().parse_args()
    validate_apply_request(apply=args.apply, context=args.context,
                           confirm_context=args.confirm_context, confirm_plan=args.confirm_plan)
    import httpx
    from pymongo import MongoClient

    with open(args.config, encoding="utf-8") as handle:
        config = json.load(handle)
    config_keys = {"database", "orders_collection", "quotas_collection",
                   "memberships_collection", "legacy_prefixes"}
    if not config_keys <= config.keys() or not isinstance(config["legacy_prefixes"], list) or not config["legacy_prefixes"]:
        raise SystemExit("Migration configuration is incomplete")
    if (any(not isinstance(prefix, str) or not prefix.strip() for prefix in config["legacy_prefixes"])
            or len(set(config["legacy_prefixes"])) != len(config["legacy_prefixes"])
            or any(not isinstance(config[key], str) or not config[key]
                   for key in ("database", "orders_collection", "quotas_collection", "memberships_collection"))):
        raise SystemExit("Migration configuration contains invalid collection names or prefixes")

    gateway = kubectl(args.context, "get", "configmap", "gateway-config", "-n", "apis", "-o", "json")
    issuer = (gateway.get("data") or {}).get("KEYCLOAK_ISSUER_URL", "").rstrip("/")
    if not issuer:
        raise SystemExit("KEYCLOAK_ISSUER_URL is missing from apis/gateway-config")
    mongo_secret = read_secret(args.context, "mongodb-app-secret", "apis")
    keycloak_secret = read_secret(args.context, "keycloak-admin-secret", "infra")
    required_mongo = {"MONGO_APP_USER", "MONGO_APP_PWD", "MONGO_APP_DATABASE", "MONGO_APP_AUTHSOURCE"}
    required_keycloak = {"ADMIN_USER", "ADMIN_PASSWORD"}
    if not required_mongo <= mongo_secret.keys() or not required_keycloak <= keycloak_secret.keys():
        raise SystemExit("Required application or Keycloak credentials are missing from Kubernetes Secrets")

    with ExitStack() as stack:
        mongo_port = start_port_forward(stack, args.context, "infra", "mongodb", 27017)
        keycloak_port = start_port_forward(stack, args.context, "infra", "keycloak", 8080)
        database_name = mongo_secret["MONGO_APP_DATABASE"]
        uri = mongo_uri(mongo_secret, mongo_port)
        try:
            mongo = MongoClient(uri, serverSelectionTimeoutMS=5000)
            database = mongo[database_name]
            database.command("ping")
            order_keys = {key for key in database[config["orders_collection"]].distinct("client_id")
                          if isinstance(key, str)}
            quota_keys = {key for key in database[config["quotas_collection"]].distinct("client_id")
                          if isinstance(key, str)}
            existing = order_keys | quota_keys
            order_counts = {key: database[config["orders_collection"]].count_documents({"client_id": key})
                            for key in existing}
            quota_counts = {key: database[config["quotas_collection"]].count_documents({"client_id": key})
                            for key in existing}
            base = f"http://127.0.0.1:{keycloak_port}/auth"
            with httpx.Client(base_url=base, timeout=15) as keycloak:
                users = keycloak_users(keycloak, issuer, keycloak_secret["ADMIN_USER"],
                                       keycloak_secret["ADMIN_PASSWORD"])
            membership_collection = database[config["memberships_collection"]]
            candidate_aliases = [
                f"{prefix}_{user['id']}" for user in users
                for prefix in config["legacy_prefixes"]
                if f"{prefix}_{user['id']}" in existing
            ]
            candidate_subjects = sorted({
                user["id"] for user in users
                if any(f"{prefix}_{user['id']}" in existing for prefix in config["legacy_prefixes"])
            })
            memberships = list(membership_collection.find(
                {"$or": [
                    {"legacy_client_ids": {"$in": candidate_aliases}},
                    {"issuer": issuer, "subject": {"$in": candidate_subjects}},
                ]} if candidate_aliases else {"_id": {"$exists": False}},
                {"_id": 0, "issuer": 1, "subject": 1, "org_id": 1,
                 "active": 1, "legacy_client_ids": 1},
            )) if candidate_aliases else []
            report = build_plan(issuer=issuer, config=config, order_counts=order_counts,
                                quota_counts=quota_counts, users=users, memberships=memberships)
            print_plan(report, args.context)

            if not args.apply:
                return 0 if report["can_apply"] else 3
            if not report["can_apply"]:
                raise SystemExit("Plan contains no safe mappings or has ambiguous/conflicting owners")
            if report["plan_sha256"] != args.confirm_plan:
                raise SystemExit("Live plan differs from the reviewed hash; rerun dry-run and review it")

            membership_collection.create_index(
                [("issuer", 1), ("subject", 1), ("org_id", 1)], unique=True)
            membership_collection.create_index("legacy_client_ids")
            for row in report["plans"]:
                aliases = [item["key"] for item in row["aliases"]]
                membership_collection.update_one(
                    {"issuer": row["issuer"], "subject": row["subject"], "org_id": row["org_id"]},
                    {"$set": {"active": True},
                     "$setOnInsert": {"org_id": row["org_id"]},
                     "$addToSet": {"legacy_client_ids": {"$each": aliases}}},
                    upsert=True,
                )
            print(f"s03_owner_migration=APPLIED memberships={len(report['plans'])} "
                  f"aliases={report['mapped_aliases']}")
            return 0
        finally:
            if "mongo" in locals():
                mongo.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"s03_owner_migration=ERROR error_type={type(exc).__name__}; details suppressed",
              file=sys.stderr)
        raise SystemExit(1) from None
