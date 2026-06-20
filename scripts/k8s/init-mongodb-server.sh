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

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROFILE_FILE="$REPO_ROOT/api/evidence-search/config/evidence-domain-profile-default.json"
NORMALIZATION_FILE="$REPO_ROOT/api/evidence-search/config/evidence-normalization-configs.json"

python3 - "$PROFILE_FILE" "$NORMALIZATION_FILE" <<'PY'
import json, sys
profile = json.load(open(sys.argv[1], encoding="utf-8"))
configs = json.load(open(sys.argv[2], encoding="utf-8"))
assert profile.get("profile_id") == "default"
assert profile.get("domains")
domains = profile["domains"]
assert len(domains) >= 1000, f"default profile requires at least 1000 domains: {len(domains)}"
domain_names = [item["domain"] for item in domains]
assert len(domain_names) == len(set(domain_names)), "default profile contains duplicate domains"
domain_counts = {category_id: 0 for category_id in range(1, 11)}
for domain in domains:
    assert any(location.get("scope") in {"global", "macroregion"} for location in domain.get("locations", [])), f"domain without global/macroregion scope: {domain['domain']}"
    for category in domain.get("categories", []):
        domain_counts[category["category_id"]] += 1
assert all(value >= 100 for value in domain_counts.values()), f"default profile requires 100 domains per category: {domain_counts}"
assert {item.get("config_type") for item in configs} == {"subcategories", "location_types", "source_types"}
subcategories = next(item for item in configs if item["config_type"] == "subcategories")
counts = {category_id: 0 for category_id in range(1, 11)}
ids = set()
for item in subcategories["items"]:
    assert item["id"] not in ids, f"duplicate subcategory id={item[id]}"
    ids.add(item["id"])
    if item.get("enabled", True):
        for category_id in item.get("category_ids", []):
            assert category_id in counts, f"unknown category_id={category_id}"
            counts[category_id] += 1
incomplete = {key: value for key, value in counts.items() if value < 10}
assert not incomplete, f"each category requires at least 10 enabled subcategories: {incomplete}"
print(f"[mongo-init] validated profile={profile['profile_id']} domains={len(profile['domains'])} normalization_docs={len(configs)} subcategories_by_category={counts} domains_by_category={domain_counts}")
PY

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

PROFILE_JSON="$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1], encoding="utf-8")), ensure_ascii=False, indent=2))' "$PROFILE_FILE")"
NORMALIZATION_JSON="$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1], encoding="utf-8")), ensure_ascii=False, indent=2))' "$NORMALIZATION_FILE")"

MONGO_JS="$(mktemp)"
trap 'rm -f "$MONGO_JS"' EXIT
cat >"$MONGO_JS" <<JS
const profile = $PROFILE_JSON;
const normalizationConfigs = $NORMALIZATION_JSON;
const keepCache = $KEEP_CACHE;
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

const profiles = appDb.getCollection("evidence_domain_profiles");
profiles.deleteMany({profile_id: profile.profile_id});
profiles.insertOne(profile);
for (const legacyIndex of ["idx_profile_docs", "uniq_profile_index", "uniq_profile_subset"]) {
  try { profiles.dropIndex(legacyIndex); } catch (error) {}
}
profiles.createIndex({profile_id: 1}, {name: "uniq_domain_profile_id", unique: true});

const storedProfile = profiles.findOne({profile_id: profile.profile_id});
if (!storedProfile || storedProfile.domains.length < 1000) throw new Error("Stored default profile requires at least 1000 domains");
const storedDomainCounts = {};
for (const domain of storedProfile.domains) {
  for (const category of (domain.categories || [])) storedDomainCounts[category.category_id] = (storedDomainCounts[category.category_id] || 0) + 1;
}
for (let categoryId = 1; categoryId <= 10; categoryId++) {
  if ((storedDomainCounts[categoryId] || 0) < 100) throw new Error("Incomplete stored domains for category_id=" + categoryId);
}

const normalization = appDb.getCollection("evidence_normalization_configs");
for (const config of normalizationConfigs) {
  normalization.replaceOne({config_type: config.config_type}, config, {upsert: true});
}
normalization.createIndex({config_type: 1}, {name: "uniq_normalization_config_type", unique: true});

const storedSubcategories = normalization.findOne({config_type: "subcategories"});
if (!storedSubcategories || String(storedSubcategories.version) !== String(normalizationConfigs.find(item => item.config_type === "subcategories").version)) {
  throw new Error("Stored subcategories version does not match the seed");
}
const storedCounts = {};
for (const item of storedSubcategories.items) {
  if (item.enabled === false) continue;
  for (const categoryId of (item.category_ids || [])) storedCounts[categoryId] = (storedCounts[categoryId] || 0) + 1;
}
for (let categoryId = 1; categoryId <= 10; categoryId++) {
  if ((storedCounts[categoryId] || 0) < 10) throw new Error("Incomplete stored subcategories for category_id=" + categoryId);
}

appDb.getCollection("news").createIndex({order_id: 1});
appDb.getCollection("news").createIndex({postId: 1});
appDb.getCollection("clients_quotas").createIndex({client_id: 1}, {unique: true});
appDb.getCollection("events").createIndex({order_id: 1});
appDb.getCollection("events").createIndex({action: 1});
appDb.getCollection("validations").createIndex({order_id: 1});
appDb.getCollection("validations").createIndex({idValidator: 1});
appDb.getCollection("validations").createIndex({idValidator: 1, order_id: 1});
appDb.getCollection("validations").createIndex(
  {order_id: 1, idAssertion: 1, idValidator: 1},
  {unique: true}
);
const cache = appDb.getCollection("evidence_search_cache");
cache.createIndex({cache_key: 1}, {unique: true});
cache.createIndex({assertion_hash: 1});
cache.createIndex({created_at: 1});
cache.createIndex({expires_at: 1}, {expireAfterSeconds: 0});
if (!keepCache) cache.deleteMany({});

print("[mongo-init] database=" + appDatabase);
print("[mongo-init] app_user=" + appUser);
print("[mongo-init] profile_id=" + profile.profile_id + " domains=" + profile.domains.length + " counts=" + JSON.stringify(storedDomainCounts));
print("[mongo-init] normalization_documents=" + normalizationConfigs.length);
print("[mongo-init] subcategories_version=" + storedSubcategories.version + " counts=" + JSON.stringify(storedCounts));
print("[mongo-init] cache_cleared=" + (!keepCache));
JS

kubectl exec -i "$POD" -n "$NAMESPACE" -- sh -c \
  'mongo_script="/tmp/mongo-init-$$.js"; cat >"$mongo_script"; mongo -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin "${MONGO_APP_DATABASE:-newsdb}" --quiet "$mongo_script"; status=$?; rm -f "$mongo_script"; exit "$status"' \
  <"$MONGO_JS"

echo "[mongo-init] completed pod=$POD namespace=$NAMESPACE"
