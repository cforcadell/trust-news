#!/usr/bin/env python3
"""Seed MongoDB evidence domain profiles for contextual domain routing.

Examples:
  scripts/k8s/apis/init-evidence-search-domains.py --source /path/to/profiles.yaml --dry-run
  scripts/k8s/apis/init-evidence-search-domains.py --source /path/to/profiles.yaml --refresh --confirm
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROFILE_ID = "default"
PROFILE_VERSION = "contextual-v3"
PROFILE_INDEX_DOC_TYPE = "profile_index"
PROFILE_SUBSET_DOC_TYPE = "profile_subset"
PROFILE_SUBSETS = ("source_types", "categories", "subcategories", "countries", "regions", "cities", "entities")
DEFAULT_DB = os.getenv("MONGO_DBNAME", "newsdb")
DEFAULT_COLLECTION = os.getenv("EVIDENCE_DOMAIN_CONFIG_COLLECTION", "evidence_domain_profiles")
DOMAIN_RE = re.compile(r"^(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}$")


def load_profiles(path: Path) -> dict[str, Any]:
    source = path
    if source.exists():
        if source.suffix.lower() == ".json":
            return json.loads(source.read_text(encoding="utf-8"))
        try:
            import yaml
        except Exception as exc:
            raise SystemExit(f"PyYAML is required to load {source}: {exc}")
        return yaml.safe_load(source.read_text(encoding="utf-8"))
    raise SystemExit(f"Source profile file not found: {source}")


def iter_preferred_domains(profiles: dict[str, Any]):
    for section in ("categories", "subcategories", "countries", "regions", "cities", "entities"):
        for profile_name, profile in (profiles.get(section) or {}).items():
            for domain in profile.get("preferred_domains") or []:
                yield section, profile_name, domain


def validate_profiles(profiles: dict[str, Any]) -> None:
    for subset in PROFILE_SUBSETS:
        if subset not in profiles:
            raise ValueError(f"{subset} is required")
        if not isinstance(profiles.get(subset), dict):
            raise ValueError(f"{subset} must be an object")

    source_types = profiles.get("source_types") or {}
    if not source_types:
        raise ValueError("source_types is required")
    for source_type, cfg in source_types.items():
        score = float((cfg or {}).get("default_trust_score", -1))
        if score < 0 or score > 1:
            raise ValueError(f"default_trust_score out of range for source_type={source_type}")

    for section in ("categories", "subcategories", "countries", "regions", "cities", "entities"):
        for profile_name, profile in (profiles.get(section) or {}).items():
            seen_domains: set[str] = set()
            for domain_cfg in profile.get("preferred_domains") or []:
                for field in ("domain", "source_type", "weight", "reason"):
                    if field not in domain_cfg:
                        raise ValueError(f"{section}.{profile_name} preferred_domain missing {field}")
                domain = str(domain_cfg["domain"]).lower().strip()
                if not DOMAIN_RE.match(domain):
                    raise ValueError(f"Invalid domain {domain} in {section}.{profile_name}")
                if domain in seen_domains:
                    raise ValueError(f"Duplicated domain {domain} in {section}.{profile_name}")
                seen_domains.add(domain)
                if domain_cfg["source_type"] not in source_types:
                    raise ValueError(f"Unknown source_type {domain_cfg['source_type']} for {domain}")
                weight = float(domain_cfg["weight"])
                if weight < 0 or weight > 1:
                    raise ValueError(f"weight out of range for {domain}")


def summarize(profiles: dict[str, Any]) -> dict[str, int]:
    return {
        "profile_documents": 1 + len(PROFILE_SUBSETS),
        "source_types": len(profiles.get("source_types") or {}),
        "categories": len(profiles.get("categories") or {}),
        "subcategories": len(profiles.get("subcategories") or {}),
        "countries": len(profiles.get("countries") or {}),
        "regions": len(profiles.get("regions") or {}),
        "cities": len(profiles.get("cities") or {}),
        "entities": len(profiles.get("entities") or {}),
        "preferred_domains": sum(1 for _ in iter_preferred_domains(profiles)),
    }


def mongo_uri_from_env() -> str:
    explicit = os.getenv("MONGO_URI")
    if explicit:
        return explicit
    user = os.getenv("MONGO_APP_USERNAME") or os.getenv("MONGO_USERNAME")
    password = os.getenv("MONGO_APP_PASSWORD") or os.getenv("MONGO_PASSWORD")
    host = os.getenv("MONGO_APP_HOST") or os.getenv("MONGO_HOST", "localhost")
    port = os.getenv("MONGO_APP_PORT") or os.getenv("MONGO_PORT", "27017")
    db = os.getenv("MONGO_APP_DATABASE") or DEFAULT_DB
    if user and password:
        return f"mongodb://{user}:{password}@{host}:{port}/{db}?authSource={db}"
    return f"mongodb://{host}:{port}/{db}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_profile_documents(
    profiles: dict[str, Any],
    source: str | Path | None = None,
    profile_id: str = PROFILE_ID,
    version: str = PROFILE_VERSION,
    updated_at: str | None = None,
) -> list[dict[str, Any]]:
    validate_profiles(profiles)
    now = updated_at or utc_now_iso()
    source_value = str(source) if source is not None else None
    docs: list[dict[str, Any]] = [
        {
            "doc_type": PROFILE_INDEX_DOC_TYPE,
            "profile_id": profile_id,
            "version": version,
            "updated_at": now,
            "source": source_value,
            "subsets": list(PROFILE_SUBSETS),
        }
    ]
    for subset in PROFILE_SUBSETS:
        docs.append(
            {
                "doc_type": PROFILE_SUBSET_DOC_TYPE,
                "profile_id": profile_id,
                "subset": subset,
                "version": version,
                "updated_at": now,
                "source": source_value,
                "items": profiles.get(subset) or {},
            }
        )
    return docs


def assemble_profiles_from_documents(docs: list[dict[str, Any]], profile_id: str = PROFILE_ID) -> dict[str, Any]:
    subsets: dict[str, Any] = {}
    for doc in docs:
        if doc.get("doc_type") != PROFILE_SUBSET_DOC_TYPE or doc.get("profile_id") != profile_id:
            continue
        subset = doc.get("subset")
        if subset in PROFILE_SUBSETS:
            subsets[subset] = doc.get("items") or {}
    missing = [subset for subset in PROFILE_SUBSETS if subset not in subsets]
    if missing:
        raise ValueError(f"Missing profile subsets for profile_id={profile_id}: {', '.join(missing)}")
    validate_profiles(subsets)
    return subsets


def create_profile_indexes(collection) -> None:
    collection.create_index([("doc_type", 1), ("profile_id", 1)], name="idx_profile_docs")
    collection.create_index(
        [("doc_type", 1), ("profile_id", 1)],
        name="uniq_profile_index",
        unique=True,
        partialFilterExpression={"doc_type": PROFILE_INDEX_DOC_TYPE},
    )
    collection.create_index(
        [("doc_type", 1), ("profile_id", 1), ("subset", 1)],
        name="uniq_profile_subset",
        unique=True,
        partialFilterExpression={"doc_type": PROFILE_SUBSET_DOC_TYPE},
    )


def apply_refresh(profiles: dict[str, Any], db_name: str, collection_name: str, source: str | Path | None = None) -> str:
    try:
        from pymongo import MongoClient
    except Exception as exc:
        raise SystemExit(f"pymongo is required for real MongoDB writes: {exc}")
    client = MongoClient(mongo_uri_from_env())
    collection = client[db_name][collection_name]
    docs = build_profile_documents(profiles, source=source)
    collection.delete_many({"profile_id": PROFILE_ID})
    collection.drop_indexes()
    collection.insert_many(docs)
    create_profile_indexes(collection)
    return "refreshed"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize contextual evidence domain profiles in MongoDB")
    parser.add_argument("--source", required=True, help="YAML or JSON source profile file")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print summary without writing")
    parser.add_argument("--refresh", action="store_true", help="Replace the evidence domain profile config for profile_id=default")
    parser.add_argument("--confirm", action="store_true", help="Required with --refresh for real writes")
    parser.add_argument("--db", default=DEFAULT_DB, help="MongoDB database")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION, help="MongoDB collection")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = Path(args.source)
    profiles = load_profiles(source)
    validate_profiles(profiles)
    summary = summarize(profiles)
    for key, value in summary.items():
        print(f"[evidence-domains] {key}={value}")
    print(f"[evidence-domains] profile_id={PROFILE_ID}")
    print(f"[evidence-domains] schema_version={PROFILE_VERSION}")
    print(f"[evidence-domains] dry_run={str(args.dry_run).lower()}")
    print(f"[evidence-domains] backend=mongo collection={args.db}.{args.collection}")

    if args.dry_run or not args.refresh:
        print("[evidence-domains] no changes applied")
        return 0
    if not args.confirm:
        print("[evidence-domains] --confirm is required with --refresh", file=sys.stderr)
        return 2
    result = apply_refresh(profiles, args.db, args.collection, source=source)
    print(f"[evidence-domains] changes_applied=true result={result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
