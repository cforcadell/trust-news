#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="infra"
POD=""
MODE="apply"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --pod) POD="$2"; shift 2 ;;
    --apply) MODE="apply"; shift ;;
    --check) MODE="check"; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$POD" ]]; then
  POD="$(kubectl get pods -n "$NAMESPACE" -l app=mongodb -o jsonpath='{.items[0].metadata.name}')"
fi
if [[ -z "$POD" ]]; then
  echo "MongoDB pod not found in namespace $NAMESPACE" >&2
  exit 1
fi

kubectl wait -n "$NAMESPACE" --for=condition=Ready "pod/$POD" --timeout=180s

MONGO_SCRIPT="$(sed "s/__MODE__/$MODE/" <<'JS'
const mode = "__MODE__";
const schemaVersion = "source-routing-storage-v2";
const appDatabase = _getEnv("MONGO_APP_DATABASE") || "newsdb";
const appDb = db.getSiblingDB(appDatabase);
const metadata = appDb.getCollection("schema_metadata");
const obsoleteCollections = [
  "source_routes",
  "evidence_search_cache",
  "evidence_domain_profiles",
  "evidence_normalization_configs"
];

function hasIndex(collection, name) {
  return collection.getIndexes().some(function(index) { return index.name === name; });
}

function aligned() {
  const currentMarker = metadata.findOne({_id: "source-routing"});
  if (!currentMarker || currentMarker.version !== schemaVersion) return false;
  const names = appDb.getCollectionNames();
  if (obsoleteCollections.some(function(name) { return names.indexOf(name) >= 0; })) return false;
  const requiredCollections = ["source_routes_v2", "domain_profiles_v1", "evidence_search_cache_v2"];
  if (requiredCollections.some(function(name) { return names.indexOf(name) < 0; })) return false;
  const routes = appDb.getCollection("source_routes_v2");
  const profiles = appDb.getCollection("domain_profiles_v1");
  const cache = appDb.getCollection("evidence_search_cache_v2");
  return hasIndex(routes, "route_key_1") &&
    hasIndex(routes, "route_signature_v2") &&
    hasIndex(profiles, "domain_1") &&
    !hasIndex(profiles, "profile_routing_v1") &&
    hasIndex(profiles, "profile_topic_codes_v1") &&
    hasIndex(profiles, "profile_evidence_kinds_v1") &&
    hasIndex(profiles, "profile_country_v1") &&
    hasIndex(cache, "cache_key_1") &&
    hasIndex(cache, "assertion_hash_1") &&
    hasIndex(cache, "created_at_1") &&
    hasIndex(cache, "expires_at_ttl");
}

if (mode === "check") {
  const ok = aligned();
  printjson({schema: schemaVersion, aligned: ok});
  quit(ok ? 0 : 1);
}

if (mode !== "apply") throw new Error("Mode must be apply or check");

if (!metadata.findOne({_id: "source-routing", version: schemaVersion})) {
  appDb.getCollection("source_routes_v2").drop();
  appDb.getCollection("domain_profiles_v1").drop();
  appDb.getCollection("evidence_search_cache_v2").drop();
}
obsoleteCollections.forEach(function(name) { appDb.getCollection(name).drop(); });

const routes = appDb.getCollection("source_routes_v2");
routes.createIndex({route_key: 1}, {name: "route_key_1", unique: true});
routes.createIndex(
  {"route_signature.topic_code": 1, "route_signature.evidence_kind": 1, "route_signature.jurisdiction_key": 1},
  {name: "route_signature_v2"}
);

const profiles = appDb.getCollection("domain_profiles_v1");
profiles.createIndex({domain: 1}, {name: "domain_1", unique: true});
if (hasIndex(profiles, "profile_routing_v1")) profiles.dropIndex("profile_routing_v1");
profiles.createIndex({topic_codes: 1}, {name: "profile_topic_codes_v1"});
profiles.createIndex({evidence_kinds: 1}, {name: "profile_evidence_kinds_v1"});
profiles.createIndex({"jurisdictions.country_code": 1}, {name: "profile_country_v1"});

const cache = appDb.getCollection("evidence_search_cache_v2");
cache.createIndex({cache_key: 1}, {name: "cache_key_1", unique: true});
cache.createIndex({assertion_hash: 1}, {name: "assertion_hash_1"});
cache.createIndex({created_at: 1}, {name: "created_at_1"});
cache.createIndex({expires_at: 1}, {name: "expires_at_ttl", expireAfterSeconds: 0});

metadata.updateOne(
  {_id: "source-routing"},
  {$set: {version: schemaVersion, aligned_at: new Date()}},
  {upsert: true}
);
printjson({schema: schemaVersion, aligned: aligned()});
JS
)"

printf '%s\n' "$MONGO_SCRIPT" | kubectl exec -i "$POD" -n "$NAMESPACE" -- sh -c \
  'mongo_script="/tmp/source-routing-realign-$$.js"; cat >"$mongo_script"; mongo -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin "${MONGO_APP_DATABASE:-newsdb}" --quiet "$mongo_script"; status=$?; rm -f "$mongo_script"; exit "$status"'

echo "[source-routing-realign] mode=$MODE pod=$POD namespace=$NAMESPACE"
