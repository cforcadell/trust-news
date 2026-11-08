#!/usr/bin/env python3
"""Conservatively map exact legacy owner keys to per-user organizations in kind.

Only a Keycloak subject whose exact configured legacy key exists in orders or
quotas is mapped. Ambiguous or unknown keys are left unmapped and remain
invisible under S03. No historical order or quota document is rewritten.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import uuid
from urllib.parse import quote_plus

import httpx
from pymongo import MongoClient


def kget(kind, name, namespace):
    raw = subprocess.check_output(["kubectl", "get", kind, name, "-n", namespace, "-o", "json"])
    return json.loads(raw)


def decoded_secret(name, namespace):
    return {key: base64.b64decode(value).decode() for key, value in kget("secret", name, namespace)["data"].items()}


def keycloak_users(issuer):
    credentials = decoded_secret("keycloak-admin-secret", "infra")
    base = "http://127.0.0.1:18080/auth"
    with httpx.Client(base_url=base, timeout=15) as client:
        token_response = client.post("/realms/master/protocol/openid-connect/token", data={
            "grant_type": "password", "client_id": "admin-cli",
            "username": credentials["ADMIN_USER"], "password": credentials["ADMIN_PASSWORD"],
        })
        token_response.raise_for_status()
        client.headers["Authorization"] = f"Bearer {token_response.json()['access_token']}"
        realm = issuer.rstrip("/").rsplit("/", 1)[-1]
        users = []
        offset = 0
        while True:
            response = client.get(f"/admin/realms/{realm}/users", params={"first": offset, "max": 100})
            response.raise_for_status()
            batch = response.json()
            users.extend(batch)
            if len(batch) < 100:
                break
            offset += len(batch)
        return [row for row in users if row.get("enabled") and row.get("id") and not row.get("username", "").startswith("service-account-")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="docs/security/s03-owner-migration.json")
    parser.add_argument("--apply-kind", action="store_true")
    args = parser.parse_args()
    context = subprocess.check_output(["kubectl", "config", "current-context"], text=True).strip()
    if not context.startswith("kind-"):
        raise SystemExit("Refusing non-kind context")
    with open(args.config, encoding="utf-8") as handle:
        config = json.load(handle)
    issuer = kget("configmap", "gateway-config", "apis")["data"]["KEYCLOAK_ISSUER_URL"]
    values = decoded_secret("mongodb-app-secret", "apis")
    user, password = quote_plus(values["MONGO_APP_USER"]), quote_plus(values["MONGO_APP_PWD"])
    auth_source = quote_plus(values["MONGO_APP_AUTHSOURCE"])
    uri = f"mongodb://{user}:{password}@127.0.0.1:27018/{config['database']}?authSource={auth_source}"
    with MongoClient(uri, serverSelectionTimeoutMS=5000) as client:
        database = client[config["database"]]
        order_keys = set(database[config["orders_collection"]].distinct("client_id"))
        quota_keys = set(database[config["quotas_collection"]].distinct("client_id"))
        existing = order_keys | quota_keys
        existing.discard(None)
        users = keycloak_users(issuer)
        plans = []
        mapped = set()
        for user_row in users:
            subject = user_row["id"]
            aliases = sorted(f"{prefix}_{subject}" for prefix in config["legacy_prefixes"] if f"{prefix}_{subject}" in existing)
            if not aliases:
                continue
            if mapped.intersection(aliases):
                raise RuntimeError("Ambiguous legacy owner mapping")
            mapped.update(aliases)
            org_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{issuer}|{subject}"))
            plans.append({"issuer": issuer, "subject": subject, "org_id": org_id,
                          "active": True, "legacy_client_ids": aliases})
        print(f"s03_owner_inventory users={len(users)} mapped_users={len(plans)} aliases={len(mapped)} "
              f"unmapped_legacy_keys={len(existing - mapped)} unmapped_order_keys={len(order_keys - mapped - {None})} "
              f"unmapped_quota_keys={len(quota_keys - mapped - {None})}")
        if args.apply_kind:
            membership = database[config["memberships_collection"]]
            membership.create_index([("issuer", 1), ("subject", 1), ("org_id", 1)], unique=True)
            membership.create_index("legacy_client_ids")
            for plan in plans:
                conflict = membership.find_one({"legacy_client_ids": {"$in": plan["legacy_client_ids"]},
                                                "$or": [{"subject": {"$ne": plan["subject"]}}, {"org_id": {"$ne": plan["org_id"]}}]})
                if conflict:
                    raise RuntimeError("Existing membership conflicts with mapped owner")
                membership.update_one({"issuer": plan["issuer"], "subject": plan["subject"], "org_id": plan["org_id"]},
                                      {"$set": {"active": True, "legacy_client_ids": plan["legacy_client_ids"]}}, upsert=True)
            print(f"s03_owner_migration=APPLIED memberships={len(plans)}")


if __name__ == "__main__":
    main()
