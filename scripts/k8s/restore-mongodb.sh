#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: restore-mongodb.sh --input FILE [--namespace NAMESPACE] [--pod POD]
                          [--apply --replace-database]

Without --apply, verifies the archive and prints the target. With both apply
flags, drops the target application database and restores the entire archive.
All writes since the backup in that database will be lost.
EOF
}

namespace=infra
pod=
input=
apply=false
replace_database=false
while (($#)); do
  case "$1" in
    --namespace|--pod|--input)
      (($# >= 2)) || { usage >&2; exit 2; }
      case "$1" in
        --namespace) namespace=$2 ;;
        --pod) pod=$2 ;;
        --input) input=$2 ;;
      esac
      shift 2 ;;
    --apply) apply=true; shift ;;
    --replace-database) replace_database=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

[[ -n $input && -f $input && -f $input.manifest ]] || { usage >&2; exit 2; }
command -v kubectl >/dev/null
command -v gzip >/dev/null
command -v sha256sum >/dev/null

database=$(sed -n 's/^database=//p' "$input.manifest")
expected=$(sed -n 's/^sha256=//p' "$input.manifest")
[[ -n $database && $database != *$'\n'* && $expected =~ ^[0-9a-f]{64}$ ]] || {
  echo 'Invalid backup manifest' >&2; exit 1;
}
[[ $database != admin && $database != config && $database != local ]] || {
  echo 'Refusing to replace a MongoDB system database' >&2; exit 1;
}
actual=$(sha256sum "$input" | cut -d ' ' -f 1)
[[ $actual == "$expected" ]] || { echo 'Backup checksum mismatch' >&2; exit 1; }
gzip -t "$input"

if [[ -z $pod ]]; then
  pod=$(kubectl get pods -n "$namespace" -l app=mongodb -o jsonpath='{.items[0].metadata.name}')
fi
[[ -n $pod ]] || { echo "MongoDB pod not found in $namespace" >&2; exit 1; }
kubectl wait -n "$namespace" --for=condition=Ready "pod/$pod" --timeout=180s >/dev/null
target=$(kubectl exec -n "$namespace" "$pod" -- sh -c 'printf %s "${MONGO_APP_DATABASE:?MONGO_APP_DATABASE is unset}"')
[[ $target == "$database" ]] || {
  echo "Database mismatch: archive=$database, target=$target" >&2; exit 1;
}

echo "Verified backup: $input (database=$database, target=$namespace/$pod)"
if [[ $apply == false ]]; then
  [[ $replace_database == false ]] || { echo '--replace-database requires --apply' >&2; exit 2; }
  echo 'Dry run: no data changed. Add --apply --replace-database to restore.'
  exit 0
fi
[[ $replace_database == true ]] || { echo '--apply requires --replace-database' >&2; exit 2; }

kubectl exec -n "$namespace" "$pod" -- sh -c \
  'command -v mongorestore >/dev/null && test -n "$MONGO_APP_USERNAME" && test -n "$MONGO_APP_PASSWORD" && mongo --quiet --username "$MONGO_INITDB_ROOT_USERNAME" --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --eval '\''if (!db.adminCommand({ping: 1}).ok) throw new Error("MongoDB ping failed")'\'''
kubectl exec -n "$namespace" "$pod" -- sh -c \
  'exec mongo --quiet --username "$MONGO_INITDB_ROOT_USERNAME" --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --eval '\''if (!db.getSiblingDB(_getEnv("MONGO_APP_DATABASE")).dropDatabase().ok) throw new Error("MongoDB dropDatabase failed")'\'''
gzip -dc "$input" | kubectl exec -i -n "$namespace" "$pod" -- sh -c \
  'exec mongorestore --username "$MONGO_INITDB_ROOT_USERNAME" --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --nsInclude "${MONGO_APP_DATABASE}.*" --archive --stopOnError'
kubectl exec -n "$namespace" "$pod" -- sh -c \
  'exec mongo --quiet --username "$MONGO_INITDB_ROOT_USERNAME" --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --eval '\''const name = _getEnv("MONGO_APP_USERNAME"); const password = _getEnv("MONGO_APP_PASSWORD"); const database = _getEnv("MONGO_APP_DATABASE"); if (!name || !password || !database) throw new Error("MongoDB app credentials are missing"); const app = db.getSiblingDB(database); if (app.getUser(name)) app.updateUser(name, {pwd: password, roles: [{role: "readWrite", db: database}]}); else app.createUser({user: name, pwd: password, roles: [{role: "readWrite", db: database}]});'\'''
echo "MongoDB restore complete: database=$database"
