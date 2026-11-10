#!/usr/bin/env bash
# Verify the S03 service credentials configured for this deployment profile.
# Secret contents are decoded only in memory and are never written to stdout.
set +x
set -euo pipefail

config="${1:-docs/security/s03-local-services.json}"
phase="${S03_PREFLIGHT_PHASE:-all}"
case "$phase" in
  infra|apis|all) ;;
  *) echo "ERROR: S03_PREFLIGHT_PHASE debe ser infra, apis o all" >&2; exit 2 ;;
esac
command -v kubectl >/dev/null || { echo "ERROR: kubectl no está disponible" >&2; exit 2; }
command -v python3 >/dev/null || { echo "ERROR: python3 no está disponible" >&2; exit 2; }

secret_value_is_usable() {
  local namespace="$1" secret="$2" key="$3" encoded value compact
  encoded="$(kubectl get secret "$secret" -n "$namespace" -o "jsonpath={.data.${key}}" 2>/dev/null || true)"
  [ -n "$encoded" ] || return 1
  value="$(printf '%s' "$encoded" | base64 -d 2>/dev/null || true)"
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
  value="$(printf '%s' "$encoded" | base64 -d 2>/dev/null || true)"
  [ "$value" = "$expected" ]
}

errors=0
checked=0
declare -A seen=()
while IFS=$'\t' read -r namespace client_id secret; do
  [ "$phase" != infra ] || continue
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

if [ "$checked" -eq 0 ] && [ "$phase" != infra ]; then
  echo "ERROR: el inventario no contiene clients S03 de servicio" >&2
  exit 2
fi
if [ "$errors" -ne 0 ]; then
  echo "Preflight S03 FALLIDO: $errors requisito(s) ausente(s) o no válido(s)." >&2
  exit 1
fi

python3 - "$config" "$phase" <<'PY'
import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

phase = sys.argv[2]
rows = [row for row in json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        if phase == "all" or row["namespace"] == phase]
errors = []

def secret(namespace, name, keys):
    result = subprocess.run(
        ["kubectl", "get", "secret", name, "-n", namespace, "-o", "json"],
        capture_output=True, text=True,
    )
    if result.returncode:
        errors.append(f"falta Secret {namespace}/{name}")
        return None
    encoded = json.loads(result.stdout).get("data", {})
    if not all(encoded.get(key) for key in keys):
        errors.append(f"faltan claves {','.join(keys)} en {namespace}/{name}")
        return None
    try:
        return {key: base64.b64decode(encoded[key], validate=True) for key in keys}
    except ValueError:
        errors.append(f"claves inválidas en {namespace}/{name}")
        return None

def openssl(*args, input_bytes=None):
    return subprocess.run(["openssl", *args], input=input_bytes, capture_output=True)

namespaces = ("infra",) if phase == "infra" else ("infra", "apis")
cas = {namespace: secret(namespace, "s03-internal-ca", ("ca.crt",))
       for namespace in namespaces}
if len(cas) == 2 and all(cas.values()) and cas["infra"]["ca.crt"] != cas["apis"]["ca.crt"]:
    errors.append("las CA S03 de infra y apis difieren")

for row in rows:
    namespace, service = row["namespace"], row["service"]
    name = f"s03-tls-{service}"
    data = secret(namespace, name, ("tls.crt", "tls.key"))
    ca = cas[namespace]
    if not data or not ca:
        continue
    cert, key = data["tls.crt"], data["tls.key"]
    if openssl("x509", "-noout", "-checkend", "86400", input_bytes=cert).returncode:
        errors.append(f"certificado caducado o inválido en {namespace}/{name}")
        continue
    san = openssl("x509", "-noout", "-ext", "subjectAltName", input_bytes=cert)
    expected_dns = f"DNS:{service}.{namespace}.svc.cluster.local"
    if san.returncode or expected_dns not in san.stdout.decode(errors="replace"):
        errors.append(f"SAN incorrecto en {namespace}/{name}")
    cert_public = openssl("x509", "-pubkey", "-noout", input_bytes=cert)
    key_public = openssl("pkey", "-pubout", input_bytes=key)
    if cert_public.returncode or key_public.returncode or cert_public.stdout != key_public.stdout:
        errors.append(f"clave y certificado no coinciden en {namespace}/{name}")
    with tempfile.TemporaryDirectory(prefix="s03-public-preflight-") as tmp:
        ca_path = Path(tmp) / "ca.crt"
        cert_path = Path(tmp) / "service.crt"
        ca_path.write_bytes(ca["ca.crt"])
        cert_path.write_bytes(cert)
        if openssl("verify", "-CAfile", str(ca_path), str(cert_path)).returncode:
            errors.append(f"cadena CA incorrecta en {namespace}/{name}")

if errors:
    for message in errors:
        print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(f"Preflight S03 FALLIDO: {len(errors)} requisito(s) TLS inválido(s).")
print(f"Preflight S03 OK: fase={phase}, servicios={len(rows)}, sin mostrar valores.")
PY
