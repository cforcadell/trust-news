#!/usr/bin/env bash
set -euo pipefail

# Prepares an authenticated SSH tunnel and a TLS-verifying kubeconfig.
# All DEPLOY_ACCESS_* inputs are supplied by the calling environment so the
# same engine can serve distinct environments without embedded identities.

required=(
  DEPLOY_ACCESS_SSH_HOST
  DEPLOY_ACCESS_SSH_PORT
  DEPLOY_ACCESS_SSH_USER
  DEPLOY_ACCESS_SSH_PRIVATE_KEY_B64
  DEPLOY_ACCESS_SSH_KNOWN_HOSTS_B64
  DEPLOY_ACCESS_KUBECONFIG_B64
  DEPLOY_ACCESS_KUBE_CA_B64
  DEPLOY_ACCESS_KUBE_CONTEXT
  DEPLOY_ACCESS_KUBE_CLUSTER
  DEPLOY_ACCESS_KUBE_TLS_SERVER_NAME
)

for name in "${required[@]}"; do
  [[ -n ${!name:-} ]] || { echo "ERROR: $name is required" >&2; exit 2; }
done

[[ ${DEPLOY_ACCESS_SSH_HOST} =~ ^[A-Za-z0-9._:-]+$ ]] || {
  echo "ERROR: DEPLOY_ACCESS_SSH_HOST is invalid" >&2; exit 2;
}
[[ ${DEPLOY_ACCESS_SSH_USER} =~ ^[A-Za-z0-9._-]+$ ]] || {
  echo "ERROR: DEPLOY_ACCESS_SSH_USER is invalid" >&2; exit 2;
}
[[ ${DEPLOY_ACCESS_SSH_PORT} =~ ^[0-9]+$ && ${DEPLOY_ACCESS_SSH_PORT} -ge 1 && ${DEPLOY_ACCESS_SSH_PORT} -le 65535 ]] || {
  echo "ERROR: DEPLOY_ACCESS_SSH_PORT is invalid" >&2; exit 2;
}
[[ ${DEPLOY_ACCESS_KUBE_CONTEXT} =~ ^[A-Za-z0-9._-]+$ && ${DEPLOY_ACCESS_KUBE_CLUSTER} =~ ^[A-Za-z0-9._-]+$ ]] || {
  echo "ERROR: Kubernetes context or cluster name is invalid" >&2; exit 2;
}
[[ ${DEPLOY_ACCESS_KUBE_TLS_SERVER_NAME} =~ ^[A-Za-z0-9._:-]+$ ]] || {
  echo "ERROR: DEPLOY_ACCESS_KUBE_TLS_SERVER_NAME is invalid" >&2; exit 2;
}

local_host=${DEPLOY_ACCESS_LOCAL_HOST:-127.0.0.1}
local_port=${DEPLOY_ACCESS_LOCAL_PORT:-6443}
remote_host=${DEPLOY_ACCESS_REMOTE_HOST:-127.0.0.1}
remote_port=${DEPLOY_ACCESS_REMOTE_PORT:-6443}
[[ $local_host == 127.0.0.1 && $remote_host == 127.0.0.1 ]] || {
  echo "ERROR: tunnel endpoints must remain loopback" >&2; exit 2;
}
[[ $local_port =~ ^[0-9]+$ && $local_port -ge 1 && $local_port -le 65535 && $remote_port =~ ^[0-9]+$ && $remote_port -ge 1 && $remote_port -le 65535 ]] || {
  echo "ERROR: tunnel port is invalid" >&2; exit 2;
}

access_dir=${DEPLOY_ACCESS_DIR:-"${CI_PROJECT_DIR:-$PWD}/.deploy-access"}
mkdir -p "$access_dir"
chmod 700 "$access_dir"

decode() {
  local value=$1 target=$2 label=$3
  printf '%s' "$value" | base64 -d > "$target" || {
    rm -f -- "$target"
    echo "ERROR: $label is not valid base64" >&2
    exit 2
  }
  [[ -s $target ]] || { echo "ERROR: $label is empty" >&2; exit 2; }
}

identity="$access_dir/identity"
known_hosts="$access_dir/known_hosts"
kubeconfig="$access_dir/kubeconfig"
ca_file="$access_dir/kube-ca.crt"
decode "$DEPLOY_ACCESS_SSH_PRIVATE_KEY_B64" "$identity" DEPLOY_ACCESS_SSH_PRIVATE_KEY_B64
decode "$DEPLOY_ACCESS_SSH_KNOWN_HOSTS_B64" "$known_hosts" DEPLOY_ACCESS_SSH_KNOWN_HOSTS_B64
decode "$DEPLOY_ACCESS_KUBECONFIG_B64" "$kubeconfig" DEPLOY_ACCESS_KUBECONFIG_B64
decode "$DEPLOY_ACCESS_KUBE_CA_B64" "$ca_file" DEPLOY_ACCESS_KUBE_CA_B64
chmod 600 "$identity" "$known_hosts" "$kubeconfig" "$ca_file"

ssh-keygen -y -f "$identity" >/dev/null 2>&1 || {
  echo "ERROR: SSH private key is invalid" >&2; exit 2;
}
ssh-keygen -F "[${DEPLOY_ACCESS_SSH_HOST}]:${DEPLOY_ACCESS_SSH_PORT}" -f "$known_hosts" >/dev/null || {
  echo "ERROR: known_hosts has no verified entry for the configured SSH host and port" >&2; exit 2;
}
openssl x509 -in "$ca_file" -noout >/dev/null 2>&1 || {
  echo "ERROR: Kubernetes CA is invalid" >&2; exit 2;
}

ssh_options=(
  -F /dev/null
  -i "$identity"
  -p "$DEPLOY_ACCESS_SSH_PORT"
  -o BatchMode=yes
  -o IdentitiesOnly=yes
  -o PreferredAuthentications=publickey
  -o PasswordAuthentication=no
  -o KbdInteractiveAuthentication=no
  -o ForwardAgent=no
  -o StrictHostKeyChecking=yes
  -o UserKnownHostsFile="$known_hosts"
  -o GlobalKnownHostsFile=/dev/null
  -o UpdateHostKeys=no
  -o ExitOnForwardFailure=yes
  -o ServerAliveInterval=30
  -o ServerAliveCountMax=3
)
ssh "${ssh_options[@]}" -f -N \
  -L "${local_host}:${local_port}:${remote_host}:${remote_port}" \
  "${DEPLOY_ACCESS_SSH_USER}@${DEPLOY_ACCESS_SSH_HOST}"

kubectl --kubeconfig "$kubeconfig" config set-cluster "$DEPLOY_ACCESS_KUBE_CLUSTER" \
  --server="https://${local_host}:${local_port}" \
  --certificate-authority="$ca_file" --embed-certs=true \
  --tls-server-name="$DEPLOY_ACCESS_KUBE_TLS_SERVER_NAME" >/dev/null
kubectl --kubeconfig "$kubeconfig" config unset \
  "clusters.${DEPLOY_ACCESS_KUBE_CLUSTER}.cluster.insecure-skip-tls-verify" >/dev/null 2>&1 || true
kubectl --kubeconfig "$kubeconfig" config use-context "$DEPLOY_ACCESS_KUBE_CONTEXT" >/dev/null

observed_server=$(kubectl --kubeconfig "$kubeconfig" config view --minify -o jsonpath='{.clusters[0].cluster.server}')
observed_skip=$(kubectl --kubeconfig "$kubeconfig" config view --minify -o jsonpath='{.clusters[0].cluster.insecure-skip-tls-verify}')
[[ $observed_server == "https://${local_host}:${local_port}" && $observed_skip != true ]] || {
  echo "ERROR: kubeconfig does not enforce the configured TLS endpoint" >&2; exit 1;
}

export KUBECONFIG="$kubeconfig"
echo "deploy_access=ready context=${DEPLOY_ACCESS_KUBE_CONTEXT} tls_server_name=${DEPLOY_ACCESS_KUBE_TLS_SERVER_NAME}"
