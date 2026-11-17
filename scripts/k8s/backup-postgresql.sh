#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: backup-postgresql.sh --output FILE [--namespace NAMESPACE] [--selector LABELS]
                            [--pod POD] [--container CONTAINER]

Streams the PostgreSQL database named by POSTGRES_DB in the selected pod to
FILE on the operator's machine. Defaults select the Keycloak database in infra.
FILE, FILE.manifest and FILE.sha256 must not exist.
EOF
}

namespace=infra
selector=app=keycloak-db
container=postgres
pod=
output=
while (($#)); do
  case "$1" in
    --namespace|--selector|--pod|--container|--output)
      (($# >= 2)) || { usage >&2; exit 2; }
      case "$1" in
        --namespace) namespace=$2 ;;
        --selector) selector=$2 ;;
        --pod) pod=$2 ;;
        --container) container=$2 ;;
        --output) output=$2 ;;
      esac
      shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

[[ -n $output && $output != */ && -n $namespace && -n $container ]] || { usage >&2; exit 2; }
command -v kubectl >/dev/null
command -v gzip >/dev/null
command -v sha256sum >/dev/null
command -v awk >/dev/null
umask 077
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/backup-artifact.sh"
source "$script_dir/postgresql-archive.sh"

postgresql_select_pod "$namespace" "$selector" "$pod"
pod=$postgresql_pod
database=$(postgresql_pod_database "$namespace" "$pod" "$container")
[[ -n $database && $database != *$'\n'* && $database != postgres && \
   $database != template0 && $database != template1 ]] || {
  echo 'Invalid or system PostgreSQL database name' >&2; exit 1;
}

backup_artifact_prepare_output "$output"
trap 'rm -f -- "$backup_artifact_temporary"' EXIT
kubectl exec -n "$namespace" "$pod" -c "$container" -- sh -ec \
  'PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is unset}" exec pg_dump \
    -h 127.0.0.1 -U "${POSTGRES_USER:?POSTGRES_USER is unset}" \
    -d "$POSTGRES_DB" --format=custom' \
  | gzip -c >"$backup_artifact_temporary"
[[ -s $backup_artifact_temporary ]] || { echo 'Empty PostgreSQL archive' >&2; exit 1; }
gzip -t "$backup_artifact_temporary"
archive_database=$(postgresql_archive_database \
  "$backup_artifact_temporary" "$namespace" "$pod" "$container")
[[ $archive_database == "$database" ]] || {
  echo 'PostgreSQL archive database differs from the selected pod' >&2; exit 1;
}
backup_artifact_finish_output "$output" postgresql "$database" "$namespace" "$pod"
trap - EXIT
checksum=$(sed -n 's/^sha256=//p' "$output.manifest")
echo "PostgreSQL backup created: $output (database=$database, sha256=$checksum)"
