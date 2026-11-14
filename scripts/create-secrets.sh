#!/usr/bin/env bash
set +x
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/create-secrets.sh [--phase infra|apis|blockchain|edge|all]

Create/update production Kubernetes Secrets from protected files outside Git.
The operation uses apply (no delete/create gap) and does not print Secret data.

Directories can be overridden with SECRETS_DIR, S03_PKI_DIR,
S03_CLIENTS_DIR, ORIGIN_TLS_CERT and ORIGIN_TLS_KEY.
EOF
}

phase=all
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
  infra|apis|blockchain|edge|all) ;;
  *) usage >&2; exit 2 ;;
esac

command -v kubectl >/dev/null || { echo 'ERROR: kubectl no está disponible' >&2; exit 2; }
command -v python3 >/dev/null || { echo 'ERROR: python3 no está disponible' >&2; exit 2; }

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
secrets_dir="${SECRETS_DIR:-$HOME/trust-news/secrets}"
s03_pki_dir="${S03_PKI_DIR:-$HOME/trust-news-secrets/s03-pki}"
s03_clients_dir="${S03_CLIENTS_DIR:-$HOME/trust-news-secrets/s03-clients}"
origin_cert="${ORIGIN_TLS_CERT:-$HOME/trustnews-origin-ca/assermetry-origin.pem}"
origin_key="${ORIGIN_TLS_KEY:-$HOME/trustnews-origin-ca/assermetry-origin.key}"
inventory="$repo_root/docs/security/s03-local-services.json"

require_file() {
  [[ -r "$1" ]] || { echo "ERROR: falta el fichero requerido: $1" >&2; exit 1; }
}

apply_env_secret() {
  local namespace="$1" name="$2" file="$3"
  kubectl create secret generic "$name" \
    --namespace "$namespace" --from-env-file="$file" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  echo "OK: actualizado $namespace/$name"
}

apply_tls_secret() {
  local namespace="$1" name="$2" cert="$3" key="$4"
  kubectl create secret tls "$name" \
    --namespace "$namespace" --cert="$cert" --key="$key" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  echo "OK: actualizado $namespace/$name"
}

apply_ca_secret() {
  local namespace="$1"
  kubectl create secret generic s03-internal-ca \
    --namespace "$namespace" --from-file=ca.crt="$s03_pki_dir/ca.crt" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  echo "OK: actualizado $namespace/s03-internal-ca"
}

need_infra() { [[ "$phase" == infra || "$phase" == all ]]; }
need_apis() { [[ "$phase" == apis || "$phase" == all ]]; }
need_blockchain() { [[ "$phase" == blockchain || "$phase" == all ]]; }
need_edge() { [[ "$phase" == edge || "$phase" == all ]]; }

# Validate all inputs for the selected phase before changing any Secret.
if need_infra; then
  for file in mongodb.env keycloak.env keycloak-db.env mongo-express.env; do
    require_file "$secrets_dir/$file"
  done
  require_file "$s03_pki_dir/ca.crt"
  require_file "$s03_pki_dir/infra-keycloak.crt"
  require_file "$s03_pki_dir/infra-keycloak.key"
  require_file "$s03_pki_dir/broker.p12"
  require_file "$s03_pki_dir/kafka-tls.env"
  require_file "$repo_root/k8s/infra/kafka/kafdrop.properties"
fi

if need_apis; then
  for file in worker-1.env worker-2.env worker-3.env generate-asertions.env \
      news-chain.env news-handler.env gateway.env mongodb.env search.env \
      mongodb-app.env source-router.env; do
    require_file "$secrets_dir/$file"
  done
  require_file "$s03_pki_dir/ca.crt"
  while IFS=$'\t' read -r namespace service; do
    [[ "$namespace" == apis ]] || continue
    require_file "$s03_pki_dir/$namespace-$service.crt"
    require_file "$s03_pki_dir/$namespace-$service.key"
  done < <(python3 - "$inventory" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as source:
    for row in json.load(source):
        print(f"{row['namespace']}\t{row['service']}")
PY
)
  while IFS=$'\t' read -r namespace client secret; do
    [[ "$namespace" == apis ]] || continue
    require_file "$s03_clients_dir/$client.env"
  done < <(python3 - "$inventory" <<'PY'
import json, sys
clients = set()
with open(sys.argv[1], encoding="utf-8") as source:
    for row in json.load(source):
        client, namespace = row.get("client"), row.get("namespace")
        if client and namespace:
            clients.add((namespace, client, row.get("secret_name", f"s03-client-{client}")))
for namespace, client, secret in sorted(clients):
    print(f"{namespace}\t{client}\t{secret}")
PY
)
fi

if need_blockchain; then
  require_file "$secrets_dir/ethereum.env"
fi
if need_edge; then
  require_file "$origin_cert"
  require_file "$origin_key"
fi

namespaces=()
need_infra && namespaces+=(infra)
need_apis && namespaces+=(apis)
need_blockchain && namespaces+=(blockchain)
need_edge && namespaces+=(kube-system)
for namespace in "${namespaces[@]}"; do
  kubectl get namespace "$namespace" >/dev/null || {
    echo "ERROR: no existe el namespace $namespace" >&2
    exit 1
  }
done

if need_infra; then
  apply_env_secret infra mongodb-secret "$secrets_dir/mongodb.env"
  apply_env_secret infra keycloak-admin-secret "$secrets_dir/keycloak.env"
  apply_env_secret infra keycloak-db-secret "$secrets_dir/keycloak-db.env"
  apply_env_secret infra mongo-express-secret "$secrets_dir/mongo-express.env"

  apply_ca_secret infra
  apply_tls_secret infra s03-tls-keycloak \
    "$s03_pki_dir/infra-keycloak.crt" "$s03_pki_dir/infra-keycloak.key"
  kubectl create secret generic s07a-kafka-broker \
    --namespace infra \
    --from-file=broker.p12="$s03_pki_dir/broker.p12" \
    --from-file=ca.crt="$s03_pki_dir/ca.crt" \
    --from-file=kafdrop.properties="$repo_root/k8s/infra/kafka/kafdrop.properties" \
    --from-env-file="$s03_pki_dir/kafka-tls.env" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  echo 'OK: actualizado infra/s07a-kafka-broker'
fi

if need_apis; then
  apply_env_secret apis validator-secret-1 "$secrets_dir/worker-1.env"
  apply_env_secret apis validator-secret-2 "$secrets_dir/worker-2.env"
  apply_env_secret apis validator-secret-3 "$secrets_dir/worker-3.env"
  apply_env_secret apis api-keys "$secrets_dir/generate-asertions.env"
  apply_env_secret apis news-chain-secrets "$secrets_dir/news-chain.env"
  apply_env_secret apis news-handler-secrets "$secrets_dir/news-handler.env"
  apply_env_secret apis gate-config "$secrets_dir/gateway.env"
  apply_env_secret apis mongodb-secret "$secrets_dir/mongodb.env"
  apply_env_secret apis search-secret "$secrets_dir/search.env"
  apply_env_secret apis mongodb-app-secret "$secrets_dir/mongodb-app.env"
  apply_env_secret apis source-router-enc "$secrets_dir/source-router.env"

  apply_ca_secret apis
  while IFS=$'\t' read -r namespace service; do
    [[ "$namespace" == apis ]] || continue
    apply_tls_secret apis "s03-tls-$service" \
      "$s03_pki_dir/$namespace-$service.crt" "$s03_pki_dir/$namespace-$service.key"
  done < <(python3 - "$inventory" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as source:
    for row in json.load(source):
        print(f"{row['namespace']}\t{row['service']}")
PY
)
  while IFS=$'\t' read -r namespace client secret; do
    [[ "$namespace" == apis ]] || continue
    apply_env_secret "$namespace" "$secret" "$s03_clients_dir/$client.env"
  done < <(python3 - "$inventory" <<'PY'
import json, sys
clients = set()
with open(sys.argv[1], encoding="utf-8") as source:
    for row in json.load(source):
        client, namespace = row.get("client"), row.get("namespace")
        if client and namespace:
            clients.add((namespace, client, row.get("secret_name", f"s03-client-{client}")))
for namespace, client, secret in sorted(clients):
    print(f"{namespace}\t{client}\t{secret}")
PY
)

  kubectl create secret generic s07a-kafka-ca \
    --namespace apis --from-file=ca.crt="$s03_pki_dir/ca.crt" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  echo 'OK: actualizado apis/s07a-kafka-ca'
fi

if need_blockchain; then
  apply_env_secret blockchain ethereum-secrets "$secrets_dir/ethereum.env"
fi

if need_edge; then
  apply_tls_secret kube-system trustnews-origin-tls "$origin_cert" "$origin_key"
fi

echo "Creación/actualización de Secrets completada: fase=$phase; no se han mostrado valores."
