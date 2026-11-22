#!/usr/bin/env python3
"""Read-only, value-redacted inventory of S03 web users or API integrations."""

from __future__ import annotations

import argparse
import sys
from contextlib import ExitStack

from scripts.security.migrate_s03_owners import (
    keycloak_admin_token, mongo_uri, read_secret, start_port_forward,
)
from scripts.security.provision_s03_gui_user import issuer_and_realm
from scripts.security.reconcile_s03_keycloak import request as keycloak_request


def args_parser() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True, help="Explicit Kubernetes context")
    parser.add_argument("--family", required=True, choices=("web", "api", "org"))
    parser.add_argument("--search", default="", help="Username, integration ID, or organization UUID substring")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--suggest-id", action="store_true",
                        help="Print the next available application-owned identifier")
    return parser.parse_args()


def safe(value, default="-") -> str:
    if value is None or value == "":
        return default
    return str(value).replace("\t", " ").replace("\n", " ").replace("\r", " ")


def next_available_id(prefix: str, existing: set[str]) -> str:
    number = 1
    while f"{prefix}-{number:03d}" in existing:
        number += 1
    return f"{prefix}-{number:03d}"


def all_keycloak_rows(client, root: str, resource: str) -> list[dict]:
    rows, first = [], 0
    while True:
        batch = keycloak_request(client, "GET", f"{root}/{resource}",
                                 params={"first": first, "max": 100})
        rows.extend(batch)
        if len(batch) < 100:
            return rows
        first += len(batch)


def user_inventory(client, root, issuer, database, search, offset, limit):
    rows, first = [], 0
    while len(rows) <= offset + limit:
        batch = keycloak_request(client, "GET", f"{root}/users", params={
            "first": first, "max": 100, **({"search": search} if search else {}),
        })
        rows.extend(row for row in batch if row.get("username") and row.get("id")
                    and not row["username"].startswith("service-account-"))
        first += len(batch)
        if len(batch) < 100:
            break
    rows = rows[offset:offset + limit]
    out = []
    for row in rows:
        username, subject = row.get("username"), row.get("id")
        if not username or not subject:
            continue
        memberships = list(database["s03_memberships"].find({"$or": [
            {"issuer": issuer, "subject": subject},
            {"legacy_client_ids": f"user_{subject}"},
        ]}, {"_id": 0, "active": 1, "org_id": 1}))
        quota = database["clients_quotas"].find_one(
            {"client_id": f"user_{subject}"}, {"_id": 0})
        active_memberships = sum(m.get("active") is True for m in memberships)
        limits = (quota or {}).get("limits") or {}
        consumed = (quota or {}).get("consumed") or {}
        out.append((safe(username), "enabled" if row.get("enabled") else "disabled",
                    "active" if active_memberships == 1 else
                    ("missing" if active_memberships == 0 else "ambiguous"),
                    safe((quota or {}).get("status"), "missing"),
                    f"news={safe(limits.get('news_generation'))}/{safe(consumed.get('news_generation'), '0')};"
                    f"blockchain={safe(limits.get('blockchain_validation'))}/{safe(consumed.get('blockchain_validation'), '0')}"))
    return out


def api_inventory(client, root, database, search, offset, limit):
    bindings = list(database["s03_integrations"].find({}, {"_id": 0}).sort("integration_id", 1))
    kc_clients, first = [], 0
    while True:
        batch = keycloak_request(client, "GET", f"{root}/clients",
                                 params={"first": first, "max": 100})
        kc_clients.extend(row for row in batch
                          if isinstance(row.get("clientId"), str)
                          and row["clientId"].startswith("tnapi-"))
        if len(batch) < 100:
            break
        first += 100
    kc_by_id = {}
    for item in kc_clients:
        client_id = item["clientId"]
        if client_id in kc_by_id:
            raise RuntimeError("Duplicate managed Keycloak client in inventory")
        kc_by_id[client_id] = item
    bindings_by_id = {row.get("integration_id"): row for row in bindings
                      if row.get("integration_id")}
    if len(bindings_by_id) != len([row for row in bindings if row.get("integration_id")]):
        raise RuntimeError("Duplicate integration binding in inventory")
    integration_ids = {item.removeprefix("tnapi-") for item in kc_by_id} | set(bindings_by_id)
    org_rows = list(database["s03_organizations"].find(
        {}, {"_id": 0, "org_id": 1, "status": 1, "limits": 1, "consumed": 1,
        "integrations": 1}))
    orgs = {row.get("org_id"): row for row in org_rows if row.get("org_id")}
    if len(orgs) != len([row for row in org_rows if row.get("org_id")]):
        raise RuntimeError("Duplicate organization record in inventory")
    results = []
    for integration_id in sorted(integration_ids):
        if search and search.casefold() not in integration_id.casefold():
            continue
        binding = bindings_by_id.get(integration_id, {})
        client_id = f"tnapi-{integration_id}"
        summary = kc_by_id.get(client_id)
        kc = (keycloak_request(client, "GET", f"{root}/clients/{summary['id']}")
              if summary else None)
        org = orgs.get(binding.get("org_id"), {})
        quota = (org.get("integrations") or {}).get(integration_id, {})
        il, ic = quota.get("limits") or {}, quota.get("consumed") or {}
        ol, oc = org.get("limits") or {}, org.get("consumed") or {}
        results.append((safe(integration_id), safe(binding.get("status"), "missing"),
                        "enabled" if kc and kc.get("enabled") else ("disabled" if kc else "missing"),
                        safe(org.get("status"), "missing"),
                        ",".join(safe(a) for a in binding.get("actions", [])) or "-",
                        safe(binding.get("expires_at")),
                        f"news={safe(il.get('news_generation'))}/{safe(ic.get('news_generation'), '0')};"
                        f"blockchain={safe(il.get('blockchain_validation'))}/{safe(ic.get('blockchain_validation'), '0')}",
                        f"news={safe(ol.get('news_generation'))}/{safe(oc.get('news_generation'), '0')};"
                        f"blockchain={safe(ol.get('blockchain_validation'))}/{safe(oc.get('blockchain_validation'), '0')}"))
    return results[offset:offset + limit]


def organization_inventory(database, search, offset, limit):
    rows = list(database["s03_organizations"].find(
        {}, {"_id": 0, "org_id": 1, "status": 1, "limits": 1,
            "consumed": 1, "reserved": 1, "integrations": 1}).sort("org_id", 1))
    if search:
        rows = [row for row in rows
                if search.casefold() in str(row.get("org_id", "")).casefold()]
    page = []
    for row in rows[offset:offset + limit]:
        limits = row.get("limits") or {}
        consumed = row.get("consumed") or {}
        reserved = row.get("reserved") or {}
        integrations = row.get("integrations") or {}
        page.append((safe(row.get("org_id")), safe(row.get("status")),
                     f"news={safe(limits.get('news_generation'))}/"
                     f"{safe(consumed.get('news_generation'), '0')}+{safe(reserved.get('news_generation'), '0')};"
                     f"blockchain={safe(limits.get('blockchain_validation'))}/"
                     f"{safe(consumed.get('blockchain_validation'), '0')}+{safe(reserved.get('blockchain_validation'), '0')}",
                     str(len(integrations)),
                     str(sum(item.get("status") == "Active"
                             for item in integrations.values() if isinstance(item, dict)))))
    return page


def main() -> int:
    args = args_parser()
    if args.offset < 0 or not 1 <= args.limit <= 100:
        raise SystemExit("offset must be >= 0 and limit must be 1..100")
    mongo_secret = read_secret(args.context, "mongodb-app-secret", "apis")
    from pymongo import MongoClient

    with ExitStack() as stack:
        mongo_port = start_port_forward(stack, args.context, "infra", "mongodb", 27017)
        with MongoClient(mongo_uri(mongo_secret, mongo_port), serverSelectionTimeoutMS=5000) as mongo:
            database = mongo[mongo_secret["MONGO_APP_DATABASE"]]
            database.command("ping")
            if args.family == "org":
                rows = organization_inventory(database, args.search, args.offset, args.limit)
                print("ORG_ID\tSTATUS\tLIMITS/USAGE\tINTEGRATIONS\tACTIVE_INTEGRATIONS")
                for row in rows:
                    print("\t".join(row))
                print(f"rows={len(rows)} offset={args.offset} limit={args.limit}; next_offset={args.offset + len(rows)}")
                return 0

            issuer, realm = issuer_and_realm(args.context)
            keycloak_secret = read_secret(args.context, "keycloak-admin-secret", "infra")
            import httpx
            keycloak_port = start_port_forward(stack, args.context, "infra", "keycloak", 8080)
            with httpx.Client(base_url=f"http://127.0.0.1:{keycloak_port}/auth", timeout=15) as client:
                token = keycloak_admin_token(client, keycloak_secret["ADMIN_USER"],
                                             keycloak_secret["ADMIN_PASSWORD"])
                client.headers["Authorization"] = f"Bearer {token}"
                root = f"/admin/realms/{realm}"
                if args.suggest_id:
                    if args.family == "web":
                        existing = {row.get("username", "").casefold()
                                    for row in all_keycloak_rows(client, root, "users")}
                        suggestion = next_available_id("user", existing)
                    else:
                        existing = {row.get("integration_id", "") for row in
                                    database["s03_integrations"].find(
                                        {}, {"_id": 0, "integration_id": 1})}
                        existing.update(
                            row.get("clientId", "").removeprefix("tnapi-")
                            for row in all_keycloak_rows(client, root, "clients")
                            if isinstance(row.get("clientId"), str)
                            and row["clientId"].startswith("tnapi-"))
                        for organization in database["s03_organizations"].find(
                                {}, {"_id": 0, "integrations": 1}):
                            existing.update((organization.get("integrations") or {}).keys())
                        suggestion = next_available_id("integration", existing)
                    print(f"suggested_id={suggestion}")
                    return 0
                headers = (("USERNAME", "ACCOUNT", "MEMBERSHIP", "QUOTA", "USAGE")
                           if args.family == "web" else
                           ("INTEGRATION", "BINDING", "KEYCLOAK", "ORG", "ACTIONS", "EXPIRES", "INTEGRATION_USAGE", "ORG_USAGE"))
                rows = (user_inventory(client, root, issuer, database, args.search, args.offset, args.limit)
                        if args.family == "web" else
                        api_inventory(client, root, database, args.search, args.offset, args.limit))
                print("\t".join(headers))
                for row in rows:
                    print("\t".join(row))
                print(f"rows={len(rows)} offset={args.offset} limit={args.limit}; next_offset={args.offset + len(rows)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"s03_inventory=ERROR type={type(exc).__name__}; details suppressed", file=sys.stderr)
        raise SystemExit(1) from None
