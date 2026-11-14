#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: sync-operations-scripts.sh --host HOST --user USER --identity FILE
       --known-hosts FILE --target-root ABSOLUTE_DIRECTORY [--port PORT]

Synchronize the versioned Hetzner operator scripts and their non-secret
support files. Private .env, certificates, keys and backups are never copied.
EOF
}

host= user= identity= known_hosts= target_root= port=22
while (($#)); do
  case "$1" in
    --host|--user|--identity|--known-hosts|--target-root|--port)
      (($# >= 2)) || { usage >&2; exit 2; }
      case "$1" in
        --host) host=$2 ;;
        --user) user=$2 ;;
        --identity) identity=$2 ;;
        --known-hosts) known_hosts=$2 ;;
        --target-root) target_root=$2 ;;
        --port) port=$2 ;;
      esac
      shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
[[ -n $host && -n $user && -n $identity && -n $known_hosts && -n $target_root ]] || {
  usage >&2; exit 2;
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../.." && pwd)"
sync_args=(--host "$host" --user "$user" --identity "$identity"
           --known-hosts "$known_hosts" --port "$port")

sync_group() {
  local destination=$1 mode=$2
  shift 2
  local sources=() relative
  for relative in "$@"; do
    sources+=("$repo_root/$relative")
  done
  "$script_dir/sync-remote-files.sh" "${sync_args[@]}" \
    --target-dir "$target_root/$destination" --mode "$mode" -- "${sources[@]}"
}

# Private host state must exist with restrictive permissions even on a new
# directory tree. Neither call synchronizes or removes its contents.
"$script_dir/sync-remote-files.sh" "${sync_args[@]}" \
  --target-dir "$target_root/secrets" --mode 0700 --directory-only
"$script_dir/sync-remote-files.sh" "${sync_args[@]}" \
  --target-dir "$target_root/secrets/pkis" --mode 0700 --directory-only

# Keep this manifest explicit: adding a file to the repository must not
# silently publish a private or local-only artifact to the operator host.
sync_group scripts 0750 \
  scripts/check_configured_secrets.sh \
  scripts/create-secrets.sh \
  scripts/print-secrets-parameters.sh
sync_group scripts/security 0750 scripts/security/check_s03_configured_secrets.sh
sync_group scripts/k8s 0750 \
  scripts/k8s/backup-mongodb.sh \
  scripts/k8s/restore-mongodb.sh \
  scripts/k8s/set-blockchain-mode.sh \
  scripts/k8s/start-k3s-cluster.sh \
  scripts/k8s/stop-k3s-cluster.sh \
  scripts/k8s/scale_env.sh
sync_group docs/security 0640 docs/security/s03-local-services.json
sync_group k8s/infra/kafka 0640 k8s/infra/kafka/kafdrop.properties
