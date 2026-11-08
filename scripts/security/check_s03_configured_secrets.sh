#!/usr/bin/env bash
# Verify the S03 service credentials configured for this deployment profile.
# Secret contents are decoded only in memory and are never written to stdout.
set +x
set -euo pipefail

config="${1:-docs/security/s03-local-services.json}"
command -v kubectl >/dev/null || { echo "ERROR: kubectl no está disponible" >&2; exit 2; }
command -v python3 >/dev/null || { echo "ERROR: python3 no está disponible" >&2; exit 2; }

secret_value_is_usable() {
  local namespace="$1" secret="$2" key="$3" encoded value compact
  encoded="$(kubectl get secret "$secret" -n "$namespace" -o "jsonpath={.data.${key}}" 2>/dev/null || true)"
  [ -n "$encoded" ] || return 1
  value="$(printf '%s' "$encoded" | base64 --decode 2>/dev/null || true)"
  compact="${value//[$'\t\r\n ']/}"
  value=
  case "${compact,,}" in
    ""|replace-me|replace_me|changeme|change-me|example|example-*|your-*|todo|xxx|xxxxxxxx)
      return 1
      ;;
  esac
}

secret_value_equals() {
  local namespace="$1" secret="$2" key="$3" expected="$4" encoded value
  encoded="$(kubectl get secret "$secret" -n "$namespace" -o "jsonpath={.data.${key}}" 2>/dev/null || true)"
  [ -n "$encoded" ] || return 1
  value="$(printf '%s' "$encoded" | base64 --decode 2>/dev/null || true)"
  [ "$value" = "$expected" ]
}

errors=0
checked=0
declare -A seen=()
while IFS=$'\t' read -r namespace client_id secret; do
  [ -n "$namespace" ] && [ -n "$client_id" ] && [ -n "$secret" ] || continue
  identity="${namespace}/${secret}"
  [ -z "${seen[$identity]+present}" ] || continue
  seen[$identity]=1
  checked=$((checked + 1))

  if ! kubectl get secret "$secret" -n "$namespace" >/dev/null 2>&1; then
    echo "ERROR: falta Secret $identity" >&2
    errors=$((errors + 1))
    continue
  fi
  if ! secret_value_equals "$namespace" "$secret" S03_CLIENT_ID "$client_id"; then
    echo "ERROR: $identity tiene S03_CLIENT_ID ausente o distinto del inventario" >&2
    errors=$((errors + 1))
  fi
  if ! secret_value_is_usable "$namespace" "$secret" S03_CLIENT_SECRET; then
    echo "ERROR: $identity requiere un S03_CLIENT_SECRET utilizable" >&2
    errors=$((errors + 1))
  fi
done < <(python3 - "$config" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    services = json.load(source)
for service in services:
    client_id = service.get("client")
    namespace = service.get("namespace")
    if client_id and namespace:
        secret = service.get("secret_name", f"s03-client-{client_id}")
        print(f"{namespace}\t{client_id}\t{secret}")
PY
)

if [ "$checked" -eq 0 ]; then
  echo "ERROR: el inventario no contiene clients S03 de servicio" >&2
  exit 2
fi
if [ "$errors" -ne 0 ]; then
  echo "Preflight S03 FALLIDO: $errors requisito(s) ausente(s) o no válido(s)." >&2
  exit 1
fi
echo "Preflight S03 OK: clients configurados, sin mostrar valores."
