#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: verify-served-tls.sh --namespace NAMESPACE --service SERVICE --port PORT
                            --server-name DNS_NAME --ca-file FILE
                            --ca-fingerprint SHA256_HEX

Checks the public certificate served by a Kubernetes Service through a local
port-forward. The trust anchor is pinned by its certificate SHA-256 fingerprint.
No Kubernetes Secret or private key is requested.
EOF
}

namespace= service= port= server_name= ca_file= ca_fingerprint=
while (($#)); do
  case "$1" in
    --namespace|--service|--port|--server-name|--ca-file|--ca-fingerprint)
      (($# >= 2)) || { usage >&2; exit 2; }
      case "$1" in
        --namespace) namespace=$2 ;;
        --service) service=$2 ;;
        --port) port=$2 ;;
        --server-name) server_name=$2 ;;
        --ca-file) ca_file=$2 ;;
        --ca-fingerprint) ca_fingerprint=$2 ;;
      esac
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

k8s_name_pattern='^[a-z0-9]([-a-z0-9]*[a-z0-9])?$'
[[ $namespace =~ $k8s_name_pattern && $service =~ $k8s_name_pattern ]] || {
  echo 'ERROR: invalid Kubernetes namespace or Service name' >&2; exit 2;
}
[[ $port =~ ^[0-9]+$ && $port -ge 1 && $port -le 65535 ]] || {
  echo 'ERROR: invalid Service port' >&2; exit 2;
}
[[ $server_name =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ && $server_name == *.* && $server_name != *..* ]] || {
  echo 'ERROR: invalid TLS server name' >&2; exit 2;
}
[[ -f $ca_file && -s $ca_file ]] || { echo 'ERROR: CA file is missing or empty' >&2; exit 2; }
for program in kubectl openssl mktemp sed timeout grep head sleep; do
  command -v "$program" >/dev/null || { echo "ERROR: $program is required" >&2; exit 2; }
done

expected=${ca_fingerprint//:/}
expected=${expected^^}
[[ $expected =~ ^[0-9A-F]{64}$ ]] || { echo 'ERROR: invalid CA SHA-256 fingerprint' >&2; exit 2; }
observed=$(openssl x509 -in "$ca_file" -noout -fingerprint -sha256 2>/dev/null) || {
  echo 'ERROR: CA file is not a certificate' >&2; exit 2;
}
observed=${observed#*=}
observed=${observed//:/}
observed=${observed^^}
[[ $observed == "$expected" ]] || { echo 'ERROR: CA fingerprint mismatch' >&2; exit 1; }
[[ $(grep -c '^-----BEGIN CERTIFICATE-----$' "$ca_file") -eq 1 ]] || {
  echo 'ERROR: CA file must contain exactly one certificate' >&2; exit 2;
}

work_dir=$(mktemp -d)
port_forward_pid=
cleanup() {
  if [[ -n $port_forward_pid ]]; then
    kill "$port_forward_pid" 2>/dev/null || true
    wait "$port_forward_pid" 2>/dev/null || true
  fi
  rm -rf -- "$work_dir"
}
trap cleanup EXIT

kubectl port-forward --address 127.0.0.1 -n "$namespace" "service/$service" ":$port" >"$work_dir/port-forward.log" 2>&1 &
port_forward_pid=$!
local_port=
for ((attempt=0; attempt<50; attempt++)); do
  local_port=$(sed -nE 's/^Forwarding from 127[.]0[.]0[.]1:([0-9]+) -> .*/\1/p' "$work_dir/port-forward.log" | head -n 1)
  [[ -n $local_port ]] && break
  kill -0 "$port_forward_pid" 2>/dev/null || {
    echo 'ERROR: port-forward ended before becoming ready' >&2; exit 1;
  }
  sleep 0.2
done
[[ -n $local_port ]] || { echo 'ERROR: port-forward did not become ready' >&2; exit 1; }

if ! timeout 20 openssl s_client \
  -connect "127.0.0.1:$local_port" \
  -servername "$server_name" \
  -verify_hostname "$server_name" \
  -verify_return_error \
  -CAfile "$ca_file" \
  -no-CApath \
  -no-CAstore \
  -brief </dev/null >"$work_dir/tls.log" 2>&1; then
  echo 'ERROR: served TLS certificate failed chain, date or hostname verification' >&2
  exit 1
fi
if ! grep -q '^Verification: OK$' "$work_dir/tls.log"; then
  echo 'ERROR: TLS handshake did not report successful certificate verification' >&2
  exit 1
fi

echo "served_tls=verified namespace=$namespace service=$service port=$port server_name=$server_name"
