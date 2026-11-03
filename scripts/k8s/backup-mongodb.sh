#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: backup-mongodb.sh --output FILE [--namespace NAMESPACE] [--pod POD]

Copies the MongoDB application database from a Kubernetes pod to FILE on the
operator's machine. FILE, FILE.manifest and FILE.sha256 must not exist.
EOF
}

namespace=infra
pod=
output=
while (($#)); do
  case "$1" in
    --namespace|--pod|--output)
      (($# >= 2)) || { usage >&2; exit 2; }
      case "$1" in
        --namespace) namespace=$2 ;;
        --pod) pod=$2 ;;
        --output) output=$2 ;;
      esac
      shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

[[ -n $output && $output != */ ]] || { usage >&2; exit 2; }
command -v kubectl >/dev/null
command -v gzip >/dev/null
command -v sha256sum >/dev/null
umask 077

if [[ -z $pod ]]; then
  pod=$(kubectl get pods -n "$namespace" -l app=mongodb -o jsonpath='{.items[0].metadata.name}')
fi
[[ -n $pod ]] || { echo "MongoDB pod not found in $namespace" >&2; exit 1; }
kubectl wait -n "$namespace" --for=condition=Ready "pod/$pod" --timeout=180s >/dev/null
database=$(kubectl exec -n "$namespace" "$pod" -- sh -c 'printf %s "${MONGO_APP_DATABASE:?MONGO_APP_DATABASE is unset}"')
[[ -n $database && $database != *$'\n'* ]] || { echo 'Invalid database name' >&2; exit 1; }
[[ $database != admin && $database != config && $database != local ]] || {
  echo 'Refusing to back up a MongoDB system database as the application database' >&2; exit 1;
}

for file in "$output" "$output.manifest" "$output.sha256"; do
  [[ ! -e $file ]] || { echo "Refusing to overwrite $file" >&2; exit 1; }
done
directory=$(dirname -- "$output")
[[ -d $directory ]] || { echo "Directory does not exist: $directory" >&2; exit 1; }
temporary=$(mktemp "$directory/.mongodb-backup.XXXXXXXX")
trap 'rm -f -- "$temporary"' EXIT

kubectl exec -n "$namespace" "$pod" -- sh -c \
  'exec mongodump --username "$MONGO_INITDB_ROOT_USERNAME" --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --db "$MONGO_APP_DATABASE" --archive' \
  | gzip -c >"$temporary"
[[ -s $temporary ]] || { echo 'Empty MongoDB archive' >&2; exit 1; }
gzip -t "$temporary"
checksum=$(sha256sum "$temporary" | cut -d ' ' -f 1)

printf 'database=%s\nnamespace=%s\npod=%s\ncreated_utc=%s\nsha256=%s\n' \
  "$database" "$namespace" "$pod" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$checksum" >"$output.manifest"
printf '%s  %s\n' "$checksum" "$(basename -- "$output")" >"$output.sha256"
mv -T -- "$temporary" "$output"
trap - EXIT
echo "MongoDB backup created: $output (database=$database, sha256=$checksum)"
