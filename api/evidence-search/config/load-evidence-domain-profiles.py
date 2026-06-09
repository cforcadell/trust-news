#!/usr/bin/env python3
"""Load contextual evidence domain profiles into MongoDB.

This loader replaces only the selected profile_id documents in the target
``evidence_domain_profiles`` collection. It preserves other profiles and
configuration. It drops ``evidence_search_cache`` by default, because profile
reloads invalidate cache keys.

Examples:
  api/evidence-search/config/load-evidence-domain-profiles.py --dry-run
  api/evidence-search/config/load-evidence-domain-profiles.py --confirm
  api/evidence-search/config/load-evidence-domain-profiles.py --source api/evidence-search/config/evidence-domain-profiles.yaml --confirm
  api/evidence-search/config/load-evidence-domain-profiles.py --profile-id custom --confirm --keep-cache
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
    """Parse CLI arguments for profile loading and backend selection."""
    # Define source, target, cache, and backend flags in one place.
    parser = argparse.ArgumentParser(description="Load evidence domain profiles in MongoDB")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="YAML or JSON profile file")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print what would be replaced without writing")
    parser.add_argument("--confirm", action="store_true", help="Required for real writes")
    parser.add_argument("--profile-id", default=init_domains.PROFILE_ID, help="Profile id to replace in the target collection")
    parser.add_argument("--db", default=init_domains.DEFAULT_DB, help="MongoDB database")
    parser.add_argument("--collection", default=init_domains.DEFAULT_COLLECTION, help="Target profile collection")
    parser.add_argument("--cache-collection", default=DEFAULT_CACHE_COLLECTION, help="Cache collection to drop after profile load")
    parser.add_argument("--keep-cache", action="store_true", help="Do not drop the evidence search cache collection")
    parser.add_argument("--backend", choices=("auto", "pymongo", "kubectl"), default="auto", help="Mongo write backend")
    parser.add_argument("--mongo-pod", default="mongodb-0", help="MongoDB pod for kubectl backend")
    parser.add_argument("--mongo-namespace", default="infra", help="MongoDB namespace for kubectl backend")
    return parser.parse_args()


def load_and_validate(source: Path) -> dict[str, Any]:
    """Load a profile file and validate its schema before writing."""
    # Reuse the shared initialization script so CLI and Kubernetes bootstrap agree.
    profiles = init_domains.load_profiles(source)
    init_domains.validate_profiles(profiles)
    return profiles


def build_docs(profiles: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    """Build Mongo documents for the selected profile id and source file."""
    # Delegate document shape construction to the shared initialization module.
    return init_domains.build_profile_documents(profiles, source=Path(args.source), profile_id=args.profile_id)


def print_summary(profiles: dict[str, Any], args: argparse.Namespace) -> None:
    """Print the profile load summary and target collections."""
    # Summarize profile content first so operators can inspect what will be written.
    summary = init_domains.summarize(profiles)
    for key, value in summary.items():
        print(f"[evidence-domains] {key}={value}")

    # Print execution settings that affect replacement and cache invalidation.
    print(f"[evidence-domains] profile_id={args.profile_id}")
    print(f"[evidence-domains] schema_version={init_domains.PROFILE_VERSION}")
    print(f"[evidence-domains] source={Path(args.source)}")
    print(f"[evidence-domains] dry_run={str(args.dry_run).lower()}")
    print(f"[evidence-domains] target={args.db}.{args.collection}")
    print(f"[evidence-domains] drop_cache={str(not args.keep_cache).lower()} collection={args.db}.{args.cache_collection}")


def reset_and_load_with_pymongo(profiles: dict[str, Any], args: argparse.Namespace) -> None:
    """Replace the selected profile documents using a direct pymongo connection."""
    # Import lazily so the kubectl backend can work without pymongo installed.
    from pymongo import MongoClient

    # Connect to the configured database and prepare profile/cache collections.
    client = MongoClient(init_domains.mongo_uri_from_env())
    database = client[args.db]
    collection = database[args.collection]
    cache_collection = database[args.cache_collection]
    docs = build_docs(profiles, args)

    # Capture pre-change counts for operator logs.
    existing_profile_docs = collection.count_documents({"profile_id": args.profile_id})
    existing_cache_docs = cache_collection.count_documents({}) if not args.keep_cache else 0

    # Replace only the selected profile id, preserving other profile configurations.
    print("[evidence-domains] backend=pymongo")
    print(f"[evidence-domains] existing_profile_docs={existing_profile_docs}")
    print(f"[evidence-domains] replacing_profile_id={args.profile_id} collection={args.db}.{args.collection}")
    deleted = collection.delete_many({"profile_id": args.profile_id})
    print(f"[evidence-domains] deleted_profile_docs={deleted.deleted_count}")

    # Drop evidence cache unless explicitly preserved, because profile versions changed.
    if not args.keep_cache:
        print(f"[evidence-domains] existing_cache_docs={existing_cache_docs}")
        print(f"[evidence-domains] dropping_collection={args.db}.{args.cache_collection}")
        cache_collection.drop()

    # Insert the new profile documents and recreate indexes required by the API.
    collection.insert_many(docs)
    init_domains.create_profile_indexes(collection)
    print(f"[evidence-domains] inserted_profile_id={args.profile_id}")
    print(f"[evidence-domains] inserted_profile_docs={len(docs)}")
    print("[evidence-domains] changes_applied=true result=profile-loaded")


def run_command(cmd: list[str], input_text: str) -> subprocess.CompletedProcess[str]:
    """Run an external command with stdin and return the completed process."""
    # Capture output so callers can filter noisy kubectl/mongo logs.
    completed = subprocess.run(cmd, input=input_text, text=True, capture_output=True, check=False)

    # Echo failures immediately to help operators diagnose backend issues.
    if completed.returncode != 0:
        if completed.stdout:
            print(completed.stdout, end="")
        if completed.stderr:
            print(completed.stderr, end="", file=sys.stderr)
    return completed


def print_relevant_output(output: str) -> None:
    """Print only evidence-domain status lines from command output."""
    # The mongo shell can be noisy; keep the operator-facing output focused.
    for line in (output or "").splitlines():
        if line.startswith("[evidence-domains]"):
            print(line)


def reset_and_load_with_kubectl(profiles: dict[str, Any], args: argparse.Namespace) -> None:
    """Replace the selected profile documents through kubectl and mongo shell."""
    # Build documents locally and embed them into the mongo shell script.
    docs = build_docs(profiles, args)
    doc_json_array = json.dumps(docs, ensure_ascii=False)

    # Run a preflight script to report existing profile/cache state before mutation.
    print("[evidence-domains] backend=kubectl")
    preflight_js = """
const targetCollection = __TARGET_COLLECTION__;
const cacheCollection = __CACHE_COLLECTION__;
const keepCache = __KEEP_CACHE__;
const profileId = __PROFILE_ID__;
const profileCol = db.getCollection(targetCollection);
const cacheCol = db.getCollection(cacheCollection);
print("[evidence-domains] existing_profile_docs=" + profileCol.countDocuments({profile_id: profileId}));
if (!keepCache) {
  print("[evidence-domains] existing_cache_docs=" + cacheCol.countDocuments({}));
  print("[evidence-domains] dropping_collection=" + db.getName() + "." + cacheCollection);
  cacheCol.drop();
}
""".replace("__TARGET_COLLECTION__", json.dumps(args.collection))
    preflight_js = preflight_js.replace("__CACHE_COLLECTION__", json.dumps(args.cache_collection))
    preflight_js = preflight_js.replace("__KEEP_CACHE__", json.dumps(bool(args.keep_cache)))
    preflight_js = preflight_js.replace("__PROFILE_ID__", json.dumps(args.profile_id))

    # Build the kubectl exec command used for both preflight and load scripts.
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

    # Build the mutation script that replaces profile docs and recreates required indexes.
    print(f"[evidence-domains] replacing_profile_id={args.profile_id} collection={args.db}.{args.collection}")
    load_js = """
const col = db.getCollection(__TARGET_COLLECTION__);
const docs = __DOCS__;
const profileId = __PROFILE_ID__;
const deleted = col.deleteMany({profile_id: profileId});
print("[evidence-domains] deleted_profile_docs=" + deleted.deletedCount);
if (docs.length > 0) {
  col.insertMany(docs);
}
try { col.dropIndex("idx_profile_docs"); } catch (e) { print("[evidence-domains] legacy_idx_profile_docs_absent=true"); }
col.createIndex(
  {doc_type: 1, profile_id: 1},
  {name: "uniq_profile_index", unique: true, partialFilterExpression: {doc_type: "profile_index"}}
);
col.createIndex(
  {doc_type: 1, profile_id: 1, subset: 1},
  {name: "uniq_profile_subset", unique: true, partialFilterExpression: {doc_type: "profile_subset"}}
);
print("[evidence-domains] inserted_profile_id=" + profileId);
print("[evidence-domains] inserted_profile_docs=" + __DOC_COUNT__);
print("[evidence-domains] changes_applied=true result=profile-loaded");
""".replace("__TARGET_COLLECTION__", json.dumps(args.collection))
    load_js = load_js.replace("__DOCS__", doc_json_array)
    load_js = load_js.replace("__PROFILE_ID__", json.dumps(args.profile_id))
    load_js = load_js.replace("__DOC_COUNT__", str(len(docs)))

    # Execute the mutation and fail loudly if mongo reports an error.
    loaded = run_command(mongo_cmd, load_js)
    print_relevant_output(loaded.stdout)
    if loaded.returncode != 0:
        raise SystemExit(f"kubectl mongo profile load failed with exit code {loaded.returncode}")


def reset_and_load(profiles: dict[str, Any], args: argparse.Namespace) -> None:
    """Choose a backend and replace the selected profile documents."""
    # Prefer pymongo for direct writes unless the user forces kubectl or pymongo is unavailable.
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

    # Use kubectl as the fallback backend for cluster-local Mongo access.
    reset_and_load_with_kubectl(profiles, args)


def main() -> int:
    """Validate arguments, optionally dry-run, and load profile documents."""
    # Parse and validate profile data before considering any destructive operation.
    args = parse_args()
    profiles = load_and_validate(Path(args.source))
    print_summary(profiles, args)

    # Dry runs stop after validation and summary output.
    if args.dry_run:
        print("[evidence-domains] no changes applied")
        return 0

    # Require an explicit confirmation flag before writing to MongoDB.
    if not args.confirm:
        print("[evidence-domains] --confirm is required for real writes", file=sys.stderr)
        return 2

    # Execute the replacement through the selected backend.
    reset_and_load(profiles, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
