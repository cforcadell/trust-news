#!/usr/bin/env python3
"""Create an application-owned S03 organization with initial usage limits."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from contextlib import ExitStack

from scripts.security.migrate_s03_owners import (
    mongo_uri, read_secret, start_port_forward, validate_apply_request,
)
from scripts.security.provision_s03_gui_user import non_negative_int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True)
    parser.add_argument("--org-id", required=True, help="Application-owned organization UUID")
    parser.add_argument("--news-generation-limit", required=True, type=non_negative_int)
    parser.add_argument("--blockchain-validation-limit", required=True, type=non_negative_int)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-context")
    parser.add_argument("--confirm-plan")
    return parser.parse_args()


def digest(plan: dict) -> str:
    data = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    args = parse_args()
    try:
        org_id = str(uuid.UUID(args.org_id))
    except ValueError:
        raise SystemExit("--org-id must be a UUID") from None
    validate_apply_request(apply=args.apply, context=args.context,
                           confirm_context=args.confirm_context,
                           confirm_plan=args.confirm_plan)
    import pymongo
    from pymongo import MongoClient

    secret = read_secret(args.context, "mongodb-app-secret", "apis")
    limits = {"news_generation": args.news_generation_limit,
              "blockchain_validation": args.blockchain_validation_limit}
    with ExitStack() as stack:
        port = start_port_forward(stack, args.context, "infra", "mongodb", 27017)
        with MongoClient(mongo_uri(secret, port), serverSelectionTimeoutMS=5000) as mongo:
            database = mongo[secret["MONGO_APP_DATABASE"]]
            database.command("ping")
            organizations = database["s03_organizations"]
            existing = organizations.find_one({"org_id": org_id}, {"_id": 0})
            plan = {"schema": 1, "context": args.context, "org_id": org_id,
                    "limits": limits, "state": "BLOCKED_EXISTS" if existing else "READY"}
            plan_hash = digest(plan)
            print(f"s03_organization_plan context={args.context} state={plan['state']} "
                  f"org_id={org_id}")
            print(f"plan_sha256={plan_hash}")
            print(f"limits news_generation={limits['news_generation']} "
                  f"blockchain_validation={limits['blockchain_validation']}")
            if not args.apply:
                return 0 if not existing else 3
            if existing or args.confirm_plan != plan_hash:
                raise SystemExit("Organization exists or its reviewed plan changed")
            organizations.create_index("org_id", unique=True)
            document = {"org_id": org_id, "status": "active", "limits": limits,
                        "consumed": {key: 0 for key in limits},
                        "reserved": {key: 0 for key in limits},
                        "integrations": {}, "quota_operations": []}
            try:
                organizations.insert_one(document)
            except pymongo.errors.DuplicateKeyError:
                raise RuntimeError("Organization ID was created concurrently") from None
            verified = organizations.find_one({"org_id": org_id}, {"_id": 0})
            if (not verified or verified.get("status") != "active"
                    or verified.get("limits") != limits
                    or verified.get("consumed") != document["consumed"]
                    or verified.get("reserved") != document["reserved"]
                    or verified.get("integrations") != {}):
                raise RuntimeError("Organization record could not be verified")
            print(f"s03_organization=APPLIED org_id={org_id} status=active")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"s03_organization=ERROR type={type(exc).__name__}; details suppressed",
              file=sys.stderr)
        raise SystemExit(1) from None
