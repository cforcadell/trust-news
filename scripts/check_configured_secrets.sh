#!/usr/bin/env bash
set +x
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: check_configured_secrets.sh --phase infra|apis

Checks the configured Kubernetes Secrets in a kind or Hetzner/K3s cluster.
It validates the live Secret objects, regardless of how they were created.
Secret values are read in memory only and are never printed.
EOF
}

phase="${SECRETS_PREFLIGHT_PHASE:-}"
while (($#)); do
  case "$1" in
    --phase)
      (($# >= 2)) || { usage >&2; exit 2; }
      phase=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

case "$phase" in
  infra|apis) ;;
  *)
    case "${PROFILE:-}" in
      infra-prod) phase=infra ;;
      apis-frontend-prod) phase=apis ;;
      *) usage >&2; exit 2 ;;
    esac
    ;;
esac

command -v kubectl >/dev/null || { echo 'ERROR: kubectl no está disponible' >&2; exit 2; }
command -v openssl >/dev/null || { echo 'ERROR: openssl no está disponible' >&2; exit 2; }
command -v base64 >/dev/null || { echo 'ERROR: base64 no está disponible' >&2; exit 2; }
context="$(kubectl config current-context 2>/dev/null || true)"
if [[ -z "$context" ]]; then
  echo 'ERROR: kubectl no tiene un contexto activo. Selecciona kind o el acceso a Hetzner.' >&2
  exit 2
fi
if ! kubectl --request-timeout=5s get --raw=/version >/dev/null 2>&1; then
  echo "ERROR: no se pudo consultar el API Kubernetes del contexto '$context'. Revisa conexión y permisos; no se validaron Secrets." >&2
  exit 2
fi
echo "Contexto Kubernetes accesible: $context; fase=$phase"

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
errors=0

secret_value_is_usable() {
  local namespace="$1" secret="$2" key="$3" encoded value compact
  key="${key//./\\.}"
  encoded="$(kubectl get secret "$secret" -n "$namespace" -o "jsonpath={.data.${key}}" 2>/dev/null || true)"
  [[ -n "$encoded" ]] || return 1
  value="$(printf '%s' "$encoded" | base64 --decode 2>/dev/null || true)"
  compact="${value//[$'\t\r\n ']/}"
  value=
  case "${compact,,}" in
    ''|replace-me|replace_me|changeme|change-me|example|example-*|your-*|todo|xxx|xxxxxxxx)
      return 1
      ;;
  esac
}

secret_key_is_present() {
  local namespace="$1" secret="$2" key="$3" encoded
  key="${key//./\\.}"
  encoded="$(kubectl get secret "$secret" -n "$namespace" -o "jsonpath={.data.${key}}" 2>/dev/null || true)"
  [[ -n "$encoded" ]] && printf '%s' "$encoded" | base64 --decode >/dev/null 2>&1
}

require_secret_exists() {
  local namespace="$1" secret="$2" error
  if error="$(kubectl get secret "$secret" -n "$namespace" -o name 2>&1 >/dev/null)"; then
    return 0
  fi
  case "$error" in
    *NotFound*|*"not found"*)
      echo "ERROR: falta Secret $namespace/$secret" >&2
      ;;
    *Forbidden*|*forbidden*|*"cannot get resource"*)
      echo "ERROR: el contexto '$context' no tiene permiso para leer Secrets en $namespace ($namespace/$secret)" >&2
      ;;
    *)
      echo "ERROR: no se pudo consultar $namespace/$secret en el contexto '$context'; revisa conexión y permisos" >&2
      ;;
  esac
  errors=$((errors + 1))
  return 1
}

require_secret_any() {
  local namespace="$1" secret="$2" key
  shift 2
  if ! require_secret_exists "$namespace" "$secret"; then
    return 0
  fi
  for key in "$@"; do
    if secret_value_is_usable "$namespace" "$secret" "$key"; then
      echo "OK: $namespace/$secret contiene una clave válida entre: $*"
      return 0
    fi
  done
  echo "ERROR: $namespace/$secret requiere al menos una clave válida entre: $*" >&2
  errors=$((errors + 1))
}

require_secret_keys() {
  local namespace="$1" secret="$2" key missing=0
  shift 2
  if ! require_secret_exists "$namespace" "$secret"; then
    return 0
  fi
  for key in "$@"; do
    if ! secret_key_is_present "$namespace" "$secret" "$key"; then
      echo "ERROR: falta la clave $key en $namespace/$secret" >&2
      missing=1
    fi
  done
  if ((missing)); then
    errors=$((errors + 1))
  else
    echo "OK: $namespace/$secret contiene las claves requeridas."
  fi
}

run_s03_preflight() {
  S03_PREFLIGHT_PHASE="$phase" bash \
    "$script_dir/security/check_s03_configured_secrets.sh" \
    "$repo_root/docs/security/s03-local-services.json"
}

check_s07a_secrets() {
  local infra_ca apis_ca encoded_password password broker_p12 certificate san eku expected kafka_errors=0

  require_secret_keys infra s07a-kafka-broker \
    broker.p12 ca.crt KEYSTORE_PASSWORD kafdrop.properties

  infra_ca="$(kubectl get secret s07a-kafka-broker -n infra -o jsonpath='{.data.ca\.crt}' 2>/dev/null || true)"
  if [[ -z "$infra_ca" ]]; then
    return 0
  fi

  # During infra deployment the APIs overlay has not created its CA Secret yet.
  # Validate that cross-phase contract only when checking the APIs phase.
  if [[ "$phase" == apis ]]; then
    require_secret_keys apis s07a-kafka-ca ca.crt
    apis_ca="$(kubectl get secret s07a-kafka-ca -n apis -o jsonpath='{.data.ca\.crt}' 2>/dev/null || true)"
    if [[ -z "$apis_ca" ]]; then
      return 0
    fi
    if ! cmp -s <(printf '%s' "$infra_ca" | base64 --decode 2>/dev/null) \
        <(printf '%s' "$apis_ca" | base64 --decode 2>/dev/null); then
      echo 'ERROR: las CA de s07a-kafka-broker y s07a-kafka-ca difieren' >&2
      errors=$((errors + 1))
      return 0
    fi
  fi
  if ! printf '%s' "$infra_ca" | base64 --decode 2>/dev/null | \
      openssl x509 -noout -checkend 86400 >/dev/null 2>&1; then
    echo 'ERROR: la CA Kafka es inválida o caduca en menos de 24 horas' >&2
    errors=$((errors + 1))
    return 0
  fi

  broker_p12="$(kubectl get secret s07a-kafka-broker -n infra -o jsonpath='{.data.broker\.p12}' 2>/dev/null || true)"
  encoded_password="$(kubectl get secret s07a-kafka-broker -n infra -o jsonpath='{.data.KEYSTORE_PASSWORD}' 2>/dev/null || true)"
  [[ -n "$broker_p12" && -n "$encoded_password" ]] || return 0
  password="$(printf '%s' "$encoded_password" | base64 --decode 2>/dev/null || true)"
  local compact_password="${password//[$'\t\r\n ']/}"
  case "${compact_password,,}" in
    ''|replace-me|replace_me|changeme|change-me|example|example-*|your-*|todo|xxx|xxxxxxxx)
    echo 'ERROR: KEYSTORE_PASSWORD de Kafka está vacío o parece un placeholder' >&2
    errors=$((errors + 1))
    return 0
      ;;
  esac
  if ! certificate="$(printf '%s\n' "$password" | openssl pkcs12 \
      -in <(printf '%s' "$broker_p12" | base64 --decode) \
      -passin stdin -clcerts -nokeys 2>/dev/null)"; then
    echo 'ERROR: broker.p12 no se puede abrir con KEYSTORE_PASSWORD' >&2
    errors=$((errors + 1))
    return 0
  fi
  password=
  if ! printf '%s' "$certificate" | openssl x509 -noout -checkend 86400 >/dev/null 2>&1; then
    echo 'ERROR: el certificado Kafka es inválido o caduca en menos de 24 horas' >&2
    errors=$((errors + 1))
    return 0
  fi
  san="$(printf '%s' "$certificate" | openssl x509 -noout -ext subjectAltName 2>/dev/null || true)"
  for expected in 'DNS:kafka.infra.svc.cluster.local' 'DNS:kafka-0.kafka.infra.svc.cluster.local'; do
    if [[ "$san" != *"$expected"* ]]; then
      echo "ERROR: el certificado Kafka no contiene SAN $expected" >&2
      kafka_errors=$((kafka_errors + 1))
    fi
  done
  eku="$(printf '%s' "$certificate" | openssl x509 -noout -ext extendedKeyUsage 2>/dev/null || true)"
  if [[ "$eku" != *'TLS Web Server Authentication'* ]]; then
    echo 'ERROR: el certificado Kafka no declara el uso serverAuth' >&2
    kafka_errors=$((kafka_errors + 1))
  fi
  if ! openssl verify \
      -CAfile <(printf '%s' "$infra_ca" | base64 --decode) \
      -verify_hostname kafka.infra.svc.cluster.local -purpose sslserver \
      <(printf '%s' "$certificate") >/dev/null 2>&1; then
    echo 'ERROR: el certificado Kafka no valida contra su CA y hostname de servicio' >&2
    kafka_errors=$((kafka_errors + 1))
  fi
  if ((kafka_errors == 0)); then
    echo 'OK: Secrets Kafka presentes; CA, PKCS12, vigencia, SAN y cadena verificados.'
  fi
  errors=$((errors + kafka_errors))
}

if ! run_s03_preflight; then
  errors=$((errors + 1))
fi
check_s07a_secrets

if [[ "$phase" == apis ]]; then
  require_secret_any apis source-router-enc OPENROUTER_API_KEY
  require_secret_any apis source-router-enc EXA_API_KEY API_KEY_PROVIDER
  require_secret_any apis api-keys OPENROUTER_API_KEY
  require_secret_any apis search-secret EXA_API_KEY API_KEY_PROVIDER

  for key in MONGO_APP_USER MONGO_APP_PWD MONGO_APP_HOST MONGO_APP_PORT MONGO_APP_DATABASE MONGO_APP_AUTHSOURCE; do
    require_secret_any apis mongodb-app-secret "$key"
  done

  for worker in 1 2 3; do
    for key in PRIVATE_KEY ACCOUNT_ADDRESS API_KEY; do
      require_secret_any apis "validator-secret-$worker" "$key"
    done
  done
fi

if ((errors != 0)); then
  echo "Preflight de Secrets FALLIDO: $errors requisito(s) ausente(s) o no válido(s)." >&2
  exit 1
fi
echo "Preflight de Secrets OK: fase=$phase; no se han mostrado valores."
