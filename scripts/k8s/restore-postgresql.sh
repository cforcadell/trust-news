#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: restore-postgresql.sh --input FILE [--namespace NAMESPACE] [--selector LABELS]
                             [--pod POD] [--container CONTAINER]
                             [--apply --replace-database]

Without --apply, verifies the archive and target without changing data. With
both apply flags, drops the target database and recreates it from the archive.
Stop all clients first; all writes since the backup will be lost.
EOF
}

namespace=infra
selector=app=keycloak-db
container=postgres
pod=
input=
apply=false
replace_database=false
while (($#)); do
  case "$1" in
    --namespace|--selector|--pod|--container|--input)
      (($# >= 2)) || { usage >&2; exit 2; }
      case "$1" in
        --namespace) namespace=$2 ;;
        --selector) selector=$2 ;;
        --pod) pod=$2 ;;
        --container) container=$2 ;;
        --input) input=$2 ;;
      esac
      shift 2 ;;
    --apply) apply=true; shift ;;
    --replace-database) replace_database=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

[[ -n $input && -n $namespace && -n $container ]] || { usage >&2; exit 2; }
command -v kubectl >/dev/null
command -v gzip >/dev/null
command -v sha256sum >/dev/null
command -v awk >/dev/null
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/backup-artifact.sh"
source "$script_dir/postgresql-archive.sh"
backup_artifact_verify_input "$input" postgresql
database=$backup_artifact_database
[[ $database != postgres && $database != template0 && $database != template1 ]] || {
  echo 'Refusing to replace a PostgreSQL system database' >&2; exit 1;
}

postgresql_select_pod "$namespace" "$selector" "$pod"
pod=$postgresql_pod
target=$(postgresql_pod_database "$namespace" "$pod" "$container")
[[ $target == "$database" ]] || {
  echo "Database mismatch: archive=$database, target=$target" >&2; exit 1;
}
archive_database=$(postgresql_archive_database "$input" "$namespace" "$pod" "$container")
[[ $archive_database == "$database" ]] || {
  echo 'PostgreSQL archive database differs from the manifest and target' >&2; exit 1;
}

echo "Verified backup: $input (database=$database, target=$namespace/$pod)"
if [[ $apply == false ]]; then
  [[ $replace_database == false ]] || { echo '--replace-database requires --apply' >&2; exit 2; }
  echo 'Dry run: no data changed. Add --apply --replace-database to restore.'
  exit 0
fi
[[ $replace_database == true ]] || { echo '--apply requires --replace-database' >&2; exit 2; }

# --create restores the archive database name, already compared to POSTGRES_DB.
# PostgreSQL refuses DROP DATABASE while clients are connected. Keep writers
# stopped throughout this operation; a failed restore needs manual recovery.
gzip -dc "$input" | kubectl exec -i -n "$namespace" "$pod" -c "$container" -- sh -ec \
  'PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is unset}" exec pg_restore \
    -h 127.0.0.1 -U "${POSTGRES_USER:?POSTGRES_USER is unset}" -d postgres \
    --clean --if-exists --create --no-owner --no-acl --exit-on-error'
echo "PostgreSQL restore complete: database=$database"
