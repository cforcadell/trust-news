#!/usr/bin/env python3
"""Provision a TrustNews GUI user through the existing TrustNewsWeb client.

Run from the repository root with ``python -m scripts.security.provision_s03_gui_user``.
The default is read-only. Apply requires the exact context and reviewed plan
hash. No Keycloak client is created or modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from scripts.security.migrate_s03_owners import (
    keycloak_admin_token, kubectl, mongo_uri, read_secret, start_port_forward,
    validate_apply_request,
)
from scripts.security.reconcile_s03_keycloak import request as keycloak_request

GUI_CLIENT = "TrustNewsWeb"
PROVISIONER_ATTRIBUTE = "trustnews_s03_gui_provisioner"
PROVISIONER_VALUE = "v1"
USERNAME_PATTERN = re.compile(r"[a-z][a-z0-9._-]{2,63}\Z")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True, help="Explicit Kubernetes context")
    parser.add_argument("--username", required=True, help="New realm username")
    parser.add_argument("--email", help="Optional email address for the realm user")
    parser.add_argument(
        "--resume-unmarked-disabled", action="store_true",
        help="Explicitly resume this disabled user after confirming it was created by a failed run",
    )
    parser.add_argument(
        "--news-generation-limit", type=non_negative_int,
        help="Maximum news-generation calls for this account (required)",
    )
    parser.add_argument(
        "--blockchain-validation-limit", type=non_negative_int,
        help="Maximum blockchain validations for this account (required)",
    )
    parser.add_argument("--apply", action="store_true", help="Apply a reviewed plan")
    parser.add_argument("--confirm-context", help="Repeat the exact Kubernetes context")
    parser.add_argument("--confirm-plan", help="SHA-256 printed by the dry run")
    return parser.parse_args()


def non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def issuer_and_realm(context: str) -> tuple[str, str]:
    gateway = kubectl(context, "get", "configmap", "gateway-config", "-n", "apis", "-o", "json")
    runtime = kubectl(context, "get", "configmap", "s03-runtime", "-n", "apis", "-o", "json")
    gateway_data = gateway.get("data") or {}
    runtime_data = runtime.get("data") or {}
    issuer = gateway_data.get("KEYCLOAK_ISSUER_URL", "").rstrip("/")
    parsed = urlsplit(issuer)
    match = re.fullmatch(r"/auth/realms/([A-Za-z0-9_-]+)", parsed.path)
    if parsed.scheme != "https" or not parsed.netloc or not match or parsed.query or parsed.fragment:
        raise RuntimeError("Gateway has an invalid public Keycloak issuer")
    realm = match.group(1)
    if realm != gateway_data.get("KEYCLOAK_REALM"):
        raise RuntimeError("Gateway realm and issuer differ")
    if (runtime_data.get("S03_ENABLED", "").lower() != "true"
            or GUI_CLIENT not in gateway_data.get("KEYCLOAK_ALLOWED_CLIENT_IDS", "").split(",")
            or GUI_CLIENT not in runtime_data.get("S03_USER_CLIENTS", "").split(",")):
        raise RuntimeError("S03 or TrustNewsWeb is not enabled in the target configuration")
    return issuer, realm


def keycloak_user(client, root: str, username: str) -> dict | None:
    rows = keycloak_request(client, "GET", f"{root}/users",
                            params={"username": username, "exact": "true"})
    matches = [row for row in rows if row.get("username", "").casefold() == username.casefold()]
    if len(matches) > 1:
        raise RuntimeError("More than one realm user matches the requested username")
    if not matches:
        return None
    return keycloak_request(client, "GET", f"{root}/users/{matches[0]['id']}")


def web_client_ready(client, root: str, required_scopes: set[str]) -> bool:
    rows = keycloak_request(client, "GET", f"{root}/clients", params={"clientId": GUI_CLIENT})
    matches = [row for row in rows if row.get("clientId") == GUI_CLIENT]
    if len(matches) != 1:
        return False
    state = keycloak_request(client, "GET", f"{root}/clients/{matches[0]['id']}")
    scopes = keycloak_request(client, "GET", f"{root}/clients/{matches[0]['id']}/default-client-scopes")
    assigned = {scope.get("name") for scope in scopes}
    return (state.get("enabled") is True and state.get("standardFlowEnabled") is True
            and required_scopes <= assigned)


def build_plan(*, context: str, issuer: str, username: str, email: str | None,
               user: dict | None, memberships: list[dict], web_ready: bool,
               resume_unmarked_disabled: bool = False,
               quota_limits: dict[str, int] | None = None,
               quota_document: dict | None = None) -> dict:
    state = "NEW"
    if user is not None:
        attributes = user.get("attributes") or {}
        marker = attributes.get(PROVISIONER_ATTRIBUTE)
        if user.get("username") != username:
            state = "BLOCKED_EXISTING_USER"
        elif (user.get("email") or None) != email:
            state = "BLOCKED_EMAIL_MISMATCH"
        else:
            subject = user["id"]
            org_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{issuer}|{subject}"))
            alias = f"user_{subject}"
            if len(memberships) > 1:
                state = "BLOCKED_MEMBERSHIP"
            expected = (issuer, subject, org_id)
            for row in memberships:
                identity = (row.get("issuer"), row.get("subject"), row.get("org_id"))
                if identity != expected or row.get("active") is not True:
                    state = "BLOCKED_MEMBERSHIP"
                    break
                if any(value != alias for value in row.get("legacy_client_ids", [])):
                    state = "BLOCKED_MEMBERSHIP"
                    break
            if state not in {"BLOCKED_MEMBERSHIP", "BLOCKED_EMAIL_MISMATCH",
                             "BLOCKED_EXISTING_USER"}:
                if user.get("enabled") is True:
                    if len(memberships) != 1:
                        state = "BLOCKED_MEMBERSHIP"
                    elif quota_document is None:
                        state = "ADD_QUOTA_ONLY"
                    else:
                        state = "ALREADY_CONFIGURED"
                elif user.get("enabled") is not False:
                    state = "BLOCKED_EXISTING_USER"
                elif memberships or marker == [PROVISIONER_VALUE]:
                    state = "RESUME_DISABLED"
                elif (resume_unmarked_disabled
                      and "UPDATE_PASSWORD" in (user.get("requiredActions") or [])):
                    state = "RESUME_UNMARKED_DISABLED"
                else:
                    state = "BLOCKED_UNMARKED_DISABLED"
    quota_matches = None
    if quota_document is not None and quota_limits is not None:
        quota_matches = (
            quota_document.get("status") == "Active"
            and quota_document.get("limits") == quota_limits
        )
        if not quota_matches:
            state = "BLOCKED_QUOTA_MISMATCH"
    if not web_ready:
        state = "BLOCKED_WEB_CLIENT"
    plan = {
        "schema_version": 3, "context": context, "issuer": issuer,
        "username": username, "email": email, "client": GUI_CLIENT, "state": state,
        "subject": user.get("id") if user else None,
        "membership_count": len(memberships),
        "resume_unmarked_disabled": resume_unmarked_disabled,
        "quota_limits": quota_limits,
        "quota_matches": quota_matches,
    }
    payload = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    plan["plan_sha256"] = hashlib.sha256(payload).hexdigest()
    plan["can_apply"] = state in {
        "NEW", "RESUME_DISABLED", "RESUME_UNMARKED_DISABLED", "ADD_QUOTA_ONLY",
    }
    return plan


def print_plan(plan: dict) -> None:
    print(f"s03_gui_plan context={plan['context']} issuer={plan['issuer']} "
          f"client={GUI_CLIENT} username={plan['username']} state={plan['state']} "
          f"email_present={plan['email'] is not None}")
    limits = plan.get("quota_limits")
    if limits is not None:
        print("quota_limits news_generation=" + str(limits["news_generation"])
              + " blockchain_validation=" + str(limits["blockchain_validation"]))
    print(f"plan_sha256={plan['plan_sha256']}")
    print("s03_gui_provision=DRY_RUN" if plan["can_apply"] else "s03_gui_provision=BLOCKED")


def private_credentials_path(root: Path, username: str, *, resume: bool) -> Path:
    path = root / "secrets" / "clients" / f"gui-{username}.json"
    for directory in (root / "secrets", root / "secrets" / "clients"):
        if directory.is_symlink():
            raise RuntimeError("Private credentials directory cannot be a symlink")
        directory.mkdir(mode=0o700, exist_ok=True)
        info = directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise RuntimeError("Private credentials directory must be owned by the operator and mode 0700")
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if (not resume or not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600):
            raise RuntimeError("Existing credentials file cannot be replaced safely")
    return path


def write_credentials(path: Path, username: str, password: str, alias: str) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"username": username, "temporary_password": password,
                       "quota_client_id": alias}, handle)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def membership_rows(collection, issuer: str, subject: str) -> list[dict]:
    alias = f"user_{subject}"
    return list(collection.find({"$or": [
        {"issuer": issuer, "subject": subject}, {"legacy_client_ids": alias},
    ]}, {"_id": 0, "issuer": 1, "subject": 1, "org_id": 1,
         "active": 1, "legacy_client_ids": 1}))


def quota_matches(quota_document: dict | None, limits: dict[str, int]) -> bool:
    return (quota_document is not None
            and quota_document.get("status") == "Active"
            and quota_document.get("limits") == limits)


def ensure_quota(collection, client_id: str, username: str,
                 limits: dict[str, int]) -> None:
    from pymongo.errors import DuplicateKeyError

    collection.create_index("client_id", unique=True)
    document = {
        "client_id": client_id,
        "name": f"GUI user {username}",
        "limits": limits,
        "consumed": {"news_generation": 0, "blockchain_validation": 0},
        "status": "Active",
        "active_date": datetime.now(timezone.utc),
        "deactivate_date": None,
    }
    try:
        collection.update_one(
            {"client_id": client_id}, {"$setOnInsert": document}, upsert=True,
        )
    except DuplicateKeyError:
        # A concurrent retry may insert the unique client key first.
        pass
    observed = collection.find_one({"client_id": client_id}, {"_id": 0})
    if not quota_matches(observed, limits):
        raise RuntimeError("Existing quota differs from the reviewed limits or is inactive")


def provision(client, root: str, username: str, email: str | None, user: dict | None,
              issuer: str, collection, credentials_path: Path,
              resume_unmarked_disabled: bool = False, quota_collection=None,
              quota_limits: dict[str, int] | None = None) -> None:
    created_by_this_run = user is None
    if created_by_this_run:
        payload = {"username": username, "enabled": False,
                   "requiredActions": ["UPDATE_PASSWORD"]}
        if email:
            payload["email"] = email
        keycloak_request(client, "POST", f"{root}/users", json=payload)
        user = keycloak_user(client, root, username)
        if user is None or user.get("enabled") is not False:
            raise RuntimeError("Created realm user was not found disabled")
    subject = user["id"]
    alias = f"user_{subject}"
    org_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{issuer}|{subject}"))
    roles = keycloak_request(client, "GET", f"{root}/users/{subject}/role-mappings/realm/composite")
    if {row.get("name") for row in roles} & {"trust-admin", "trust-read-all"}:
        raise RuntimeError("GUI user has privileged realm roles and cannot be enabled")
    # Recheck resumed users before touching MongoDB. New users are trusted here
    # only because this invocation created them while keeping them disabled.
    if not created_by_this_run:
        rows = membership_rows(collection, issuer, subject)
        quota_document = (quota_collection.find_one({"client_id": alias}, {"_id": 0})
                          if quota_collection is not None else None)
        check = build_plan(
            context="apply", issuer=issuer, username=username, email=email,
            user=user, memberships=rows, web_ready=True,
            resume_unmarked_disabled=resume_unmarked_disabled,
            quota_limits=quota_limits, quota_document=quota_document,
        )
        if not check["can_apply"]:
            raise RuntimeError("Existing disabled user cannot be resumed safely")

    password = secrets.token_urlsafe(36)
    keycloak_request(client, "PUT", f"{root}/users/{subject}/reset-password",
                     json={"type": "password", "temporary": True, "value": password})
    write_credentials(credentials_path, username, password, alias)
    if quota_collection is not None and quota_limits is not None:
        ensure_quota(quota_collection, alias, username, quota_limits)
    collection.create_index([("issuer", 1), ("subject", 1), ("org_id", 1)], unique=True)
    collection.create_index("legacy_client_ids")
    collection.update_one(
        {"issuer": issuer, "subject": subject, "org_id": org_id, "active": True},
        {"$addToSet": {"legacy_client_ids": alias}}, upsert=True,
    )
    if not collection.find_one({"issuer": issuer, "subject": subject, "org_id": org_id,
                                "active": True, "legacy_client_ids": alias}, {"_id": 1}):
        raise RuntimeError("GUI membership could not be verified")
    keycloak_request(client, "PUT", f"{root}/users/{subject}", json={"enabled": True})
    verified = keycloak_request(client, "GET", f"{root}/users/{subject}")
    if verified.get("enabled") is not True:
        raise RuntimeError("Realm user did not become enabled")
    print(f"s03_gui_provision=APPLIED client={GUI_CLIENT} username={username} "
          f"membership=active quota=active "
          f"news_generation_limit={quota_limits['news_generation'] if quota_limits else 'unset'} "
          f"blockchain_validation_limit={quota_limits['blockchain_validation'] if quota_limits else 'unset'} "
          f"credentials_file={credentials_path}")


def main() -> int:
    args = parse_args()
    if not USERNAME_PATTERN.fullmatch(args.username) or args.username.startswith("service-account-"):
        raise SystemExit("Username must be 3-64 lowercase letters, digits, dots, underscores or hyphens; service-account- is reserved")
    if args.email is not None and (not args.email or "@" not in args.email or any(c.isspace() for c in args.email)):
        raise SystemExit("Email is invalid")
    if args.news_generation_limit is None or args.blockchain_validation_limit is None:
        raise SystemExit("Both --news-generation-limit and --blockchain-validation-limit are required")
    validate_apply_request(apply=args.apply, context=args.context,
                           confirm_context=args.confirm_context, confirm_plan=args.confirm_plan)

    import httpx
    from pymongo import MongoClient

    repo_root = Path(__file__).resolve().parents[2]
    issuer, realm = issuer_and_realm(args.context)
    with (repo_root / "docs/security/s03-keycloak-clients.json").open(encoding="utf-8") as handle:
        client_config = json.load(handle)
    if client_config.get("realm") != realm or GUI_CLIENT not in client_config.get("user_clients", []):
        raise RuntimeError("Local client inventory differs from the target realm")
    required_scopes = {"trustnews-gateway-audience"} | {
        f"s03-aud-{audience}" for audience in client_config["user_audiences"]
    }
    mongo_secret = read_secret(args.context, "mongodb-app-secret", "apis")
    keycloak_secret = read_secret(args.context, "keycloak-admin-secret", "infra")
    required_mongo = {"MONGO_APP_USER", "MONGO_APP_PWD", "MONGO_APP_DATABASE", "MONGO_APP_AUTHSOURCE"}
    if not required_mongo <= mongo_secret.keys() or not {"ADMIN_USER", "ADMIN_PASSWORD"} <= keycloak_secret.keys():
        raise RuntimeError("Required application or Keycloak credentials are missing")

    with ExitStack() as stack:
        mongo_port = start_port_forward(stack, args.context, "infra", "mongodb", 27017)
        keycloak_port = start_port_forward(stack, args.context, "infra", "keycloak", 8080)
        with MongoClient(mongo_uri(mongo_secret, mongo_port), serverSelectionTimeoutMS=5000) as mongo:
            database = mongo[mongo_secret["MONGO_APP_DATABASE"]]
            database.command("ping")
            collection = database["s03_memberships"]
            quota_collection = database["clients_quotas"]
            base = f"http://127.0.0.1:{keycloak_port}/auth"
            with httpx.Client(base_url=base, timeout=15) as client:
                token = keycloak_admin_token(client, keycloak_secret["ADMIN_USER"],
                                             keycloak_secret["ADMIN_PASSWORD"])
                client.headers["Authorization"] = f"Bearer {token}"
                root = f"/admin/realms/{realm}"
                realm_state = keycloak_request(client, "GET", root)
                if realm_state.get("registrationEmailAsUsername") is True:
                    raise RuntimeError("Realm uses email as username; this username policy cannot provision it")
                if realm_state.get("verifyEmail") is True and not args.email:
                    raise RuntimeError("Realm requires email verification; provide --email")
                web_ready = web_client_ready(client, root, required_scopes)
                user = keycloak_user(client, root, args.username)
                rows = membership_rows(collection, issuer, user["id"]) if user else []
                limits = {
                    "news_generation": args.news_generation_limit,
                    "blockchain_validation": args.blockchain_validation_limit,
                }
                quota_document = (
                    quota_collection.find_one({"client_id": f"user_{user['id']}"}, {"_id": 0})
                    if user else None
                )
                plan = build_plan(context=args.context, issuer=issuer,
                                  username=args.username, email=args.email,
                                  user=user, memberships=rows, web_ready=web_ready,
                                  resume_unmarked_disabled=args.resume_unmarked_disabled,
                                  quota_limits=limits, quota_document=quota_document)
                print_plan(plan)
                if not args.apply:
                    return 0 if plan["can_apply"] else 3
                if not plan["can_apply"] or plan["plan_sha256"] != args.confirm_plan:
                    raise SystemExit("Live plan is blocked or differs from the reviewed hash")
                limits = {
                    "news_generation": args.news_generation_limit,
                    "blockchain_validation": args.blockchain_validation_limit,
                }
                quota_collection = database["clients_quotas"]
                if plan["state"] == "ADD_QUOTA_ONLY":
                    alias = f"user_{user['id']}"
                    ensure_quota(quota_collection, alias, args.username, limits)
                    print(f"s03_gui_provision=APPLIED client={GUI_CLIENT} username={args.username} "
                          f"mode=quota_only quota=active "
                          f"news_generation_limit={limits['news_generation']} "
                          f"blockchain_validation_limit={limits['blockchain_validation']}")
                    return 0
                credentials_path = private_credentials_path(
                    repo_root, args.username,
                    resume=plan["state"] in {
                        "RESUME_DISABLED", "RESUME_UNMARKED_DISABLED",
                    },
                )
                provision(client, root, args.username, args.email, user,
                          issuer, collection, credentials_path,
                          resume_unmarked_disabled=args.resume_unmarked_disabled,
                          quota_collection=quota_collection, quota_limits=limits)
                return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"s03_gui_provision=ERROR error_type={type(exc).__name__}; "
              "details suppressed; inspect the target account and quota before retry",
              file=sys.stderr)
        raise SystemExit(1) from None
