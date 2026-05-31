#!/usr/bin/env python3
"""Reset and load contextual evidence domain profiles into MongoDB.

This loader is intentionally destructive only for derived/config collections:
- drops the target evidence_domain_profiles collection before loading
- drops evidence_search_cache by default, because profile reloads invalidate cache keys

Examples:
  api/evidence-search/config/load-evidence-domain-profiles.py --dry-run
  api/evidence-search/config/load-evidence-domain-profiles.py --confirm
  api/evidence-search/config/load-evidence-domain-profiles.py --source api/evidence-search/config/evidence-domain-profiles.yaml --confirm
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE = Path(__file__).resolve().with_name("evidence-domain-profiles.yaml")
INIT_SCRIPT = REPO_ROOT / "scripts" / "k8s" / "apis" / "init-evidence-search-domains.py"
DEFAULT_CACHE_COLLECTION = "evidence_search_cache"

spec = importlib.util.spec_from_file_location("init_evidence_search_domains", INIT_SCRIPT)
init_domains = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(init_domains)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reset and load evidence domain profiles in MongoDB")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="YAML or JSON profile file")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print what would be replaced without writing")
    parser.add_argument("--confirm", action="store_true", help="Required for the real reset/load")
    parser.add_argument("--db", default=init_domains.DEFAULT_DB, help="MongoDB database")
    parser.add_argument("--collection", default=init_domains.DEFAULT_COLLECTION, help="Target profile collection")
    parser.add_argument("--cache-collection", default=DEFAULT_CACHE_COLLECTION, help="Cache collection to drop after profile reset")
    parser.add_argument("--keep-cache", action="store_true", help="Do not drop the evidence search cache collection")
    parser.add_argument("--backend", choices=("auto", "pymongo", "kubectl"), default="auto", help="Mongo write backend")
    parser.add_argument("--mongo-pod", default="mongodb-0", help="MongoDB pod for kubectl backend")
    parser.add_argument("--mongo-namespace", default="infra", help="MongoDB namespace for kubectl backend")
    return parser.parse_args()


def load_and_validate(source: Path) -> dict[str, Any]:
    profiles = init_domains.load_profiles(source)
    init_domains.validate_profiles(profiles)
    return profiles


def build_docs(profiles: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    return init_domains.build_profile_documents(profiles, source=Path(args.source))


def print_summary(profiles: dict[str, Any], args: argparse.Namespace) -> None:
    summary = init_domains.summarize(profiles)
    for key, value in summary.items():
        print(f"[evidence-domains] {key}={value}")
    print(f"[evidence-domains] profile_id={init_domains.PROFILE_ID}")
    print(f"[evidence-domains] schema_version={init_domains.PROFILE_VERSION}")
    print(f"[evidence-domains] source={Path(args.source)}")
    print(f"[evidence-domains] dry_run={str(args.dry_run).lower()}")
    print(f"[evidence-domains] target={args.db}.{args.collection}")
    print(f"[evidence-domains] drop_cache={str(not args.keep_cache).lower()} collection={args.db}.{args.cache_collection}")


def reset_and_load_with_pymongo(profiles: dict[str, Any], args: argparse.Namespace) -> None:
    from pymongo import MongoClient

    client = MongoClient(init_domains.mongo_uri_from_env())
    database = client[args.db]
    collection = database[args.collection]
    cache_collection = database[args.cache_collection]
    docs = build_docs(profiles, args)

    existing_profile_docs = collection.count_documents({})
    existing_cache_docs = cache_collection.count_documents({}) if not args.keep_cache else 0

    print("[evidence-domains] backend=pymongo")
    print(f"[evidence-domains] existing_profile_docs={existing_profile_docs}")
    print(f"[evidence-domains] dropping_collection={args.db}.{args.collection}")
    collection.drop()

    if not args.keep_cache:
        print(f"[evidence-domains] existing_cache_docs={existing_cache_docs}")
        print(f"[evidence-domains] dropping_collection={args.db}.{args.cache_collection}")
        cache_collection.drop()

    collection.insert_many(docs)
    init_domains.create_profile_indexes(collection)
    print(f"[evidence-domains] inserted_profile_id={init_domains.PROFILE_ID}")
    print(f"[evidence-domains] inserted_profile_docs={len(docs)}")
    print("[evidence-domains] changes_applied=true result=reset-loaded")


def run_command(cmd: list[str], input_text: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(cmd, input=input_text, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        if completed.stdout:
            print(completed.stdout, end="")
        if completed.stderr:
            print(completed.stderr, end="", file=sys.stderr)
    return completed


def print_relevant_output(output: str) -> None:
    for line in (output or "").splitlines():
        if line.startswith("[evidence-domains]"):
            print(line)


def reset_and_load_with_kubectl(profiles: dict[str, Any], args: argparse.Namespace) -> None:
    docs = build_docs(profiles, args)
    doc_json_array = json.dumps(docs, ensure_ascii=False)

    print("[evidence-domains] backend=kubectl")
    preflight_js = """
const targetCollection = __TARGET_COLLECTION__;
const cacheCollection = __CACHE_COLLECTION__;
const keepCache = __KEEP_CACHE__;
const profileCol = db.getCollection(targetCollection);
const cacheCol = db.getCollection(cacheCollection);
print("[evidence-domains] existing_profile_docs=" + profileCol.countDocuments({}));
if (!keepCache) {
  print("[evidence-domains] existing_cache_docs=" + cacheCol.countDocuments({}));
  print("[evidence-domains] dropping_collection=" + db.getName() + "." + cacheCollection);
  cacheCol.drop();
}
""".replace("__TARGET_COLLECTION__", json.dumps(args.collection))
    preflight_js = preflight_js.replace("__CACHE_COLLECTION__", json.dumps(args.cache_collection))
    preflight_js = preflight_js.replace("__KEEP_CACHE__", json.dumps(bool(args.keep_cache)))

    mongo_cmd = [
        "kubectl",
        "exec",
        "-i",
        args.mongo_pod,
        "-n",
        args.mongo_namespace,
        "--",
        "sh",
        "-c",
        f'mongo -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin {args.db} --quiet',
    ]
    preflight = run_command(mongo_cmd, preflight_js)
    print_relevant_output(preflight.stdout)
    if preflight.returncode != 0:
        raise SystemExit(f"kubectl mongo preflight failed with exit code {preflight.returncode}")

    print(f"[evidence-domains] dropping_collection={args.db}.{args.collection}")
    import_cmd = [
        "kubectl",
        "exec",
        "-i",
        args.mongo_pod,
        "-n",
        args.mongo_namespace,
        "--",
        "sh",
        "-c",
        'mongoimport -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" '
        f'--authenticationDatabase admin --db {args.db} --collection {args.collection} --drop --jsonArray',
    ]
    imported = run_command(import_cmd, doc_json_array)
    if imported.returncode != 0:
        raise SystemExit(f"kubectl mongoimport failed with exit code {imported.returncode}")

    index_js = """
const col = db.getCollection(__TARGET_COLLECTION__);
col.createIndex({doc_type: 1, profile_id: 1}, {name: "idx_profile_docs"});
col.createIndex(
  {doc_type: 1, profile_id: 1},
  {name: "uniq_profile_index", unique: true, partialFilterExpression: {doc_type: "profile_index"}}
);
col.createIndex(
  {doc_type: 1, profile_id: 1, subset: 1},
  {name: "uniq_profile_subset", unique: true, partialFilterExpression: {doc_type: "profile_subset"}}
);
print("[evidence-domains] inserted_profile_id=default");
print("[evidence-domains] inserted_profile_docs=" + __DOC_COUNT__);
print("[evidence-domains] changes_applied=true result=reset-loaded");
""".replace("__TARGET_COLLECTION__", json.dumps(args.collection))
    index_js = index_js.replace("__DOC_COUNT__", str(len(docs)))
    indexed = run_command(mongo_cmd, index_js)
    print_relevant_output(indexed.stdout)
    if indexed.returncode != 0:
        raise SystemExit(f"kubectl mongo index creation failed with exit code {indexed.returncode}")


def reset_and_load(profiles: dict[str, Any], args: argparse.Namespace) -> None:
    if args.backend in {"auto", "pymongo"}:
        try:
            reset_and_load_with_pymongo(profiles, args)
            return
        except ModuleNotFoundError as exc:
            if args.backend == "pymongo":
                raise SystemExit(f"pymongo is required for --backend=pymongo: {exc}")
            print(f"[evidence-domains] pymongo_unavailable={exc}; falling back to kubectl")
        except Exception:
            if args.backend == "pymongo":
                raise
            print("[evidence-domains] pymongo backend failed; falling back to kubectl", file=sys.stderr)

    reset_and_load_with_kubectl(profiles, args)


def main() -> int:
    args = parse_args()
    profiles = load_and_validate(Path(args.source))
    print_summary(profiles, args)

    if args.dry_run:
        print("[evidence-domains] no changes applied")
        return 0
    if not args.confirm:
        print("[evidence-domains] --confirm is required because this loader drops the target collection first", file=sys.stderr)
        return 2

    reset_and_load(profiles, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
