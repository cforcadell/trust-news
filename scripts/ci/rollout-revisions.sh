#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo 'Usage: rollout-revisions.sh capture --targets "namespace/deployment ..." --snapshot FILE' >&2
  echo '       rollout-revisions.sh restore --snapshot FILE' >&2
  exit 2
}

(($# > 0)) || usage
action=$1
shift
targets= snapshot=
while (($#)); do
  case "$1" in
    --targets|--snapshot)
      (($# >= 2)) || usage
      case "$1" in
        --targets) targets=$2 ;;
        --snapshot) snapshot=$2 ;;
      esac
      shift 2
      ;;
    *) usage ;;
  esac
done
[[ $action == capture || $action == restore ]] || usage
[[ -n $snapshot ]] || usage
[[ $action != capture || -n $targets ]] || usage
[[ $action != restore || -z $targets ]] || usage

validate_target() {
  local target=$1
  [[ $target =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?/[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] || {
    echo "ERROR: invalid deployment target: $target" >&2
    exit 2
  }
}

revision_of() {
  local target=$1 namespace=${1%%/*} name=${1#*/} revision
  revision=$(kubectl get deployment "$name" -n "$namespace" \
    -o jsonpath='{.metadata.annotations.deployment\.kubernetes\.io/revision}')
  [[ $revision =~ ^[1-9][0-9]*$ ]] || {
    echo "ERROR: deployment has no rollout revision: $target" >&2
    exit 1
  }
  printf '%s' "$revision"
}

if [[ $action == capture ]]; then
  tmp=$(mktemp)
  trap 'rm -f -- "$tmp"' EXIT
  declare -A seen=()
  for target in $targets; do
    validate_target "$target"
    [[ ! -v seen[$target] ]] || { echo "ERROR: duplicate deployment: $target" >&2; exit 2; }
    seen[$target]=1
    revision=$(revision_of "$target")
    printf '%s\t%s\n' "$target" "$revision" >> "$tmp"
  done
  [[ -s $tmp ]] || { echo 'ERROR: no deployments captured' >&2; exit 2; }
  mv -- "$tmp" "$snapshot"
  trap - EXIT
  echo "rollout_snapshot=captured deployments=${#seen[@]}"
  exit 0
fi

[[ -s $snapshot ]] || { echo 'ERROR: rollout snapshot is missing or empty' >&2; exit 1; }
declare -A seen=()
plan=()
while IFS=$'\t' read -r target previous extra; do
  [[ -n $target && -z ${extra:-} ]] || { echo 'ERROR: malformed rollout snapshot' >&2; exit 2; }
  validate_target "$target"
  [[ $previous =~ ^[1-9][0-9]*$ && ! -v seen[$target] ]] || {
    echo 'ERROR: malformed or duplicate rollout revision' >&2; exit 2;
  }
  seen[$target]=1
  current=$(revision_of "$target")
  if (( current == previous )); then
    continue
  fi
  if (( current != previous + 1 )); then
    echo "ERROR: unexpected revision change for $target ($previous -> $current)" >&2
    exit 1
  fi
  plan+=("$target:$previous")
done < "$snapshot"
[[ ${#seen[@]} -gt 0 ]] || { echo 'ERROR: empty rollout snapshot' >&2; exit 2; }

# Validate every undo before changing any Deployment.
for entry in "${plan[@]}"; do
  target=${entry%:*}
  previous=${entry#*:}
  kubectl rollout undo "deployment/${target#*/}" -n "${target%%/*}" \
    --to-revision="$previous" --dry-run=server >/dev/null
done
for entry in "${plan[@]}"; do
  target=${entry%:*}
  previous=${entry#*:}
  kubectl rollout undo "deployment/${target#*/}" -n "${target%%/*}" \
    --to-revision="$previous"
done
echo "rollout_snapshot=restored deployments=${#plan[@]}"
