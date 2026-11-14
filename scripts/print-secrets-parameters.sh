#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo 'Usage: print-secrets-parameters.sh [DIRECTORY]' >&2
  echo 'Lists .env parameter names, never values.' >&2
}

if (($# > 1)); then usage; exit 2; fi
if [[ ${1:-} == -h || ${1:-} == --help ]]; then usage; exit 0; fi
base_dir="${1:-${SECRETS_DIR:-$HOME/trust-news/secrets}}"
[[ -d $base_dir ]] || { echo "ERROR: no existe el directorio: $base_dir" >&2; exit 2; }
base_dir="$(cd -- "$base_dir" && pwd)"

find "$base_dir" -type f \( -name '*.env' -o -name '.env*' \) \
  ! -name '*.bak' ! -name '*.backup' ! -name '*.tmp' -print0 |
  sort -z |
  while IFS= read -r -d '' env_file; do
    relative="${env_file#"$base_dir"/}"
    printf '\n## %s\n\n' "$relative"
    awk '
      /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
      /^[[:space:]]*(export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*[[:space:]]*=/ {
        line=$0
        sub(/^[[:space:]]*export[[:space:]]+/, "", line)
        sub(/^[[:space:]]*/, "", line)
        sub(/[[:space:]]*=.*/, "", line)
        print "- " line "=<informar>"
        found=1
      }
      END { if (!found) print "- Sin parámetros definidos" }
    ' "$env_file" | sort -u
  done
