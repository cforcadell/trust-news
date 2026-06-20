#!/usr/bin/env python3
"""Validate and load one-document evidence profiles plus normalization configs."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "api"))
sys.path.insert(0, str(REPO_ROOT / "api" / "evidence-search"))

from common.models.evidence_models import EvidenceDomainProfile, EvidenceNormalizationConfig
from app.domain_router.profiles_loader import CONFIG_TYPES, validate_profile_references

PROFILE_ID = "default"
PROFILE_VERSION = "weighted-v1"
DEFAULT_DB = os.getenv("MONGO_DBNAME", "newsdb")
DEFAULT_COLLECTION = os.getenv("EVIDENCE_DOMAIN_CONFIG_COLLECTION", "evidence_domain_profiles")
DEFAULT_NORMALIZATION_COLLECTION = os.getenv("EVIDENCE_NORMALIZATION_CONFIG_COLLECTION", "evidence_normalization_configs")
DEFAULT_PROFILE_SOURCE = REPO_ROOT / "api/evidence-search/config/evidence-domain-profile-default.json"
DEFAULT_NORMALIZATION_SOURCE = REPO_ROOT / "api/evidence-search/config/evidence-normalization-configs.json"


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_profiles(path: Path) -> dict[str, Any]:
    return load_json(path)


def load_configs(path: Path) -> dict[str, EvidenceNormalizationConfig]:
    docs = load_json(path)
    configs = {doc["config_type"]: EvidenceNormalizationConfig.model_validate(doc) for doc in docs}
    missing = set(CONFIG_TYPES) - set(configs)
    if missing:
        raise ValueError(f"Missing normalization configs: {sorted(missing)}")
    return configs


def validate_profiles(profile_doc: dict[str, Any], configs=None) -> None:
    profile = EvidenceDomainProfile.model_validate(profile_doc)
    if configs is not None:
        validate_profile_references(profile, configs)


def build_profile_documents(profile_doc: dict[str, Any], **_kwargs) -> list[dict[str, Any]]:
    profile = EvidenceDomainProfile.model_validate(profile_doc)
    return [profile.model_dump(mode="json")]


def summarize(profile_doc: dict[str, Any]) -> dict[str, int]:
    profile = EvidenceDomainProfile.model_validate(profile_doc)
    return {"profile_documents": 1, "preferred_domains": len(profile.domains)}


def mongo_uri_from_env() -> str:
    explicit = os.getenv("MONGO_URI")
    if explicit:
        return explicit
    user = os.getenv("MONGO_APP_USERNAME") or os.getenv("MONGO_USERNAME")
    password = os.getenv("MONGO_APP_PASSWORD") or os.getenv("MONGO_PASSWORD")
    host = os.getenv("MONGO_APP_HOST") or os.getenv("MONGO_HOST", "localhost")
    port = os.getenv("MONGO_APP_PORT") or os.getenv("MONGO_PORT", "27017")
    db = os.getenv("MONGO_APP_DATABASE") or DEFAULT_DB
    auth = f"{user}:{password}@" if user and password else ""
    suffix = f"?authSource={db}" if auth else ""
    return f"mongodb://{auth}{host}:{port}/{db}{suffix}"


def create_profile_indexes(collection) -> None:
    for legacy_name in ("idx_profile_docs", "uniq_profile_index", "uniq_profile_subset"):
        try:
            collection.drop_index(legacy_name)
        except Exception:
            pass
    collection.create_index("profile_id", name="uniq_domain_profile_id", unique=True)


def apply_refresh(profile_doc, config_docs, db_name, collection_name, normalization_collection_name):
    from pymongo import MongoClient
    db = MongoClient(mongo_uri_from_env())[db_name]
    profile = EvidenceDomainProfile.model_validate(profile_doc).model_dump(mode="json")
    db[collection_name].delete_many({"profile_id": profile["profile_id"]})
    db[collection_name].insert_one(profile)
    create_profile_indexes(db[collection_name])
    for config in config_docs:
        parsed = EvidenceNormalizationConfig.model_validate(config).model_dump(mode="json")
        db[normalization_collection_name].replace_one({"config_type": parsed["config_type"]}, parsed, upsert=True)
    db[normalization_collection_name].create_index("config_type", name="uniq_normalization_config_type", unique=True)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(DEFAULT_PROFILE_SOURCE))
    parser.add_argument("--normalization-source", default=str(DEFAULT_NORMALIZATION_SOURCE))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--normalization-collection", default=DEFAULT_NORMALIZATION_COLLECTION)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    profile_doc = load_json(args.source)
    config_docs = load_json(args.normalization_source)
    configs = load_configs(Path(args.normalization_source))
    validate_profiles(profile_doc, configs)
    print(f"[evidence-domains] profile_id={profile_doc['profile_id']} profile_documents=1 normalization_documents={len(config_docs)}")
    if args.dry_run or not args.refresh:
        print("[evidence-domains] no changes applied")
        return 0
    if not args.confirm:
        print("[evidence-domains] --confirm is required with --refresh", file=sys.stderr)
        return 2
    apply_refresh(profile_doc, config_docs, args.db, args.collection, args.normalization_collection)
    print("[evidence-domains] changes_applied=true result=profile-loaded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
