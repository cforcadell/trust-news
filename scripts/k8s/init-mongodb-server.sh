#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="infra"
POD=""
KEEP_CACHE=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --pod) POD="$2"; shift 2 ;;
    --keep-cache) KEEP_CACHE=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ "$DRY_RUN" == true ]]; then
  echo "[mongo-init] dry_run=true no changes applied"
  exit 0
fi

if [[ -z "$POD" ]]; then
  POD="$(kubectl get pods -n "$NAMESPACE" -l app=mongodb -o jsonpath='{.items[0].metadata.name}')"
fi
if [[ -z "$POD" ]]; then
  echo "MongoDB pod not found in namespace $NAMESPACE" >&2
  exit 1
fi

kubectl wait -n "$NAMESPACE" --for=condition=Ready "pod/$POD" --timeout=180s

MONGO_SCRIPT="$(sed "s/__KEEP_CACHE__/$KEEP_CACHE/" <<'JS'
const keepCache = __KEEP_CACHE__;
const appUser = _getEnv("MONGO_APP_USERNAME") || "app_trust_user";
const appPassword = _getEnv("MONGO_APP_PASSWORD");
const appDatabase = _getEnv("MONGO_APP_DATABASE") || "newsdb";
if (!appPassword) throw new Error("MONGO_APP_PASSWORD is required");
const appDb = db.getSiblingDB(appDatabase);

if (appDb.getUser(appUser)) {
  appDb.updateUser(appUser, {pwd: appPassword, roles: [{role: "readWrite", db: appDatabase}]});
} else {
  appDb.createUser({user: appUser, pwd: appPassword, roles: [{role: "readWrite", db: appDatabase}]});
}

// ISSUE-015 migration: the static allowlist is no longer active.
appDb.getCollection("evidence_domain_profiles").drop();
appDb.getCollection("evidence_normalization_configs").drop();

appDb.getCollection("news").createIndex({order_id: 1});
appDb.getCollection("news").createIndex({postId: 1});
appDb.getCollection("clients_quotas").createIndex({client_id: 1}, {unique: true});
appDb.getCollection("events").createIndex({order_id: 1});
appDb.getCollection("events").createIndex({action: 1});
appDb.getCollection("validations").createIndex({order_id: 1});
appDb.getCollection("validations").createIndex({idValidator: 1});
appDb.getCollection("validations").createIndex({idValidator: 1, order_id: 1});
appDb.getCollection("validations").createIndex({order_id: 1, idAssertion: 1, idValidator: 1}, {unique: true});

const routes = appDb.getCollection("source_routes");
routes.createIndex({route_key: 1}, {name: "route_key_1", unique: true});
routes.createIndex({"route_signature.claim_type": 1, "route_signature.subcategory": 1, "route_signature.country_code": 1, "route_signature.region_code": 1});

const cache = appDb.getCollection("evidence_search_cache");
cache.createIndex({cache_key: 1}, {unique: true});
cache.createIndex({assertion_hash: 1});
cache.createIndex({created_at: 1});
cache.createIndex({expires_at: 1}, {expireAfterSeconds: 0});
if (!keepCache) cache.deleteMany({});

print("[mongo-init] database=" + appDatabase);
print("[mongo-init] app_user=" + appUser);
print("[mongo-init] legacy_profiles_dropped=true");
print("[mongo-init] source_routes_ready=true");
print("[mongo-init] cache_cleared=" + (!keepCache));
JS
)"

printf '%s\n' "$MONGO_SCRIPT" | kubectl exec -i "$POD" -n "$NAMESPACE" -- sh -c \
  'mongo_script="/tmp/mongo-init-$$.js"; cat >"$mongo_script"; mongo -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin "${MONGO_APP_DATABASE:-newsdb}" --quiet "$mongo_script"; status=$?; rm -f "$mongo_script"; exit "$status"'

echo "[mongo-init] completed pod=$POD namespace=$NAMESPACE"
