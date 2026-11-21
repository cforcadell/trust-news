#!/usr/bin/env python3
"""Preview or assign validation deadlines to legacy pending orders.

Requires the same MongoDB environment variables as News Handler. The default
mode is read-only; --apply writes deadlines, then the normal reconciler closes
expired orders. No order is closed by this script.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))
from common.utils.mongo import build_mongo_uri_from_env  # noqa: E402


def parse_timestamp(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("missing or invalid timestamp")
    if parsed.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=int, required=True, help="Deadline used for legacy orders (1..1440)")
    parser.add_argument("--apply", action="store_true", help="Persist deadlines; default is dry-run")
    args = parser.parse_args()
    if not 1 <= args.minutes <= 1440:
        parser.error("--minutes must be between 1 and 1440")
    if not os.getenv("MONGO_URI") and not (os.getenv("MONGO_APP_USER") and os.getenv("MONGO_APP_PWD")):
        parser.error("MongoDB credentials must be supplied through the News Handler environment")

    now = datetime.now(timezone.utc)
    counts = {"eligible": 0, "already_expired": 0, "missing_start": 0, "updated": 0, "conflict": 0}
    with MongoClient(build_mongo_uri_from_env(), serverSelectionTimeoutMS=5000) as client:
        db = client[os.getenv("MONGO_DBNAME", "newsdb")]
        orders = db[os.getenv("MONGO_COLLECTION", "orders")]
        events = db[os.getenv("MONGO_EVENTS_COLLECTION", "events")]
        cursor = orders.find(
            {"status": "VALIDATION_PENDING", "validation_deadline_at": {"$exists": False}},
            {"order_id": 1, "validation_started_at": 1, "validation_revision": 1},
        )
        for order in cursor:
            try:
                if order.get("validation_started_at"):
                    started = parse_timestamp(order["validation_started_at"])
                else:
                    event = events.find_one(
                        {"order_id": order["order_id"], "action": {"$in": ["light_validation_request", "blockchain_registered"]}},
                        sort=[("timestamp", 1)],
                    )
                    started = parse_timestamp(event["timestamp"] if event else None)
            except (ValueError, TypeError):
                counts["missing_start"] += 1
                continue
            deadline = started + timedelta(minutes=args.minutes)
            counts["eligible"] += 1
            counts["already_expired"] += int(deadline <= now)
            if not args.apply:
                continue
            fields = {
                "validation_started_at": started.isoformat(),
                "validation_deadline_at": deadline,
                "validation_deadline_minutes": args.minutes,
            }
            if "validation_revision" not in order:
                fields["validation_revision"] = 0
            revision_filter = (order["validation_revision"] if "validation_revision" in order
                               else {"$exists": False})
            result = orders.update_one(
                {"_id": order["_id"], "status": "VALIDATION_PENDING", "validation_deadline_at": {"$exists": False},
                 "validation_revision": revision_filter},
                {"$set": fields},
            )
            counts["updated" if result.modified_count else "conflict"] += 1
    print(f"mode={'apply' if args.apply else 'dry-run'} " + " ".join(f"{key}={value}" for key, value in counts.items()))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"validation_deadline_backfill=ERROR error_type={type(exc).__name__}; details suppressed", file=sys.stderr)
        raise SystemExit(1) from None
