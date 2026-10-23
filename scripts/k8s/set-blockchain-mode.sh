#!/usr/bin/env bash
set -euo pipefail

# Run after the core infrastructure and API manifests have been applied.
# BLOCKCHAIN_ENABLED=ON|OFF is the single deployment switch.
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
if [ -n "${SKAFFOLD_BIN:-}" ]; then
  skaffold_bin="$SKAFFOLD_BIN"
elif command -v skaffold >/dev/null 2>&1; then
  skaffold_bin="skaffold"
elif [ -x "$repo_root/skaffold" ]; then
  skaffold_bin="$repo_root/skaffold"
else
  echo "Skaffold was not found. Install it or set SKAFFOLD_BIN to its executable path." >&2
  exit 127
fi

mode="${BLOCKCHAIN_ENABLED:-OFF}"
case "${mode^^}" in
  ON|TRUE|1) enabled=true ;;
  OFF|FALSE|0) enabled=false ;;
  *) echo "BLOCKCHAIN_ENABLED must be ON or OFF" >&2; exit 2 ;;
esac

chain_nodes=(geth-bootnode geth-miner geth-rpc-endpoint)
validator_workers=(validate-worker-1 validate-worker-2 validate-worker-3)

set_mode_config() {
  kubectl create configmap blockchain-mode -n apis \
    --from-literal="BLOCKCHAIN_ENABLED=$1" --dry-run=client -o yaml | kubectl apply -f -
}

restart_and_wait() {
  kubectl rollout restart "deployment/$1" -n apis
  kubectl rollout status "deployment/$1" -n apis --timeout=300s
}

gate_new_orders() {
  set_mode_config false
  restart_and_wait news-handler
  restart_and_wait gateway
}

check_pending_orders() {
  local pending
  pending="$(kubectl exec -i -n apis deployment/news-handler -- python - <<'PY'
import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from common.utils.mongo import build_mongo_uri_from_env

async def main():
    client = AsyncIOMotorClient(build_mongo_uri_from_env(), serverSelectionTimeoutMS=5000)
    collection = client[os.getenv("MONGO_DBNAME", "newsdb")][os.getenv("MONGO_COLLECTION", "news")]
    count = await collection.count_documents({
        "$or": [{"validation_mode": "BLOCKCHAIN"}, {"validation_mode": {"$exists": False}}],
        "status": {"$in": ["CREATED", "ASSERTIONS_REQUESTED", "DOCUMENT_CREATED",
                           "IPFS_PENDING", "IPFS_UPLOADED", "BLOCKCHAIN_REQUESTED",
                           "BLOCKCHAIN_PENDING", "VALIDATION_PENDING"]},
    })
    print(count)
    client.close()

asyncio.run(main())
PY
)"
  if ! [[ "$pending" =~ ^[0-9]+$ ]]; then
    echo "Could not read pending blockchain order count: $pending" >&2
    exit 1
  fi
  if [ "$pending" -gt 0 ]; then
    echo "Cannot disable blockchain: $pending orders are still in progress." >&2
    exit 1
  fi
}

if [ "${1:-}" = "--check-pending" ]; then
  check_pending_orders
  exit 0
fi
if [ "${1:-}" = "--gate" ]; then
  gate_new_orders
  exit 0
fi

set_application_flag() {
  local value="$1"
  set_mode_config "$value"
  for deployment in news-handler "${validator_workers[@]}" gateway; do
    restart_and_wait "$deployment"
  done
}

if [ "$enabled" = true ]; then
  blockchain_profile="${BLOCKCHAIN_PROFILE:-blockchain}"
  if [ "${PROFILE:-}" = "apis-frontend-prod" ]; then
    blockchain_profile="${BLOCKCHAIN_PROFILE:-blockchain-prod}"
  fi
  # Apply manifests only when absent: reapplying their zero-replica template
  # would interrupt an already running chain during an ordinary API rollout.
  for node in "${chain_nodes[@]}"; do
    if ! kubectl get "statefulset/$node" -n blockchain >/dev/null 2>&1; then
      "$skaffold_bin" deploy -p "$blockchain_profile"
      break
    fi
  done
  for node in "${chain_nodes[@]}"; do
    kubectl scale "statefulset/$node" --replicas=1 -n blockchain
    kubectl rollout status "statefulset/$node" -n blockchain --timeout=300s
  done
  if [ "${PROFILE:-}" = "apis-frontend-prod" ]; then
    test -f build.json || { echo "build.json is required to deploy news-chain-prod" >&2; exit 1; }
    "$skaffold_bin" deploy -p news-chain-prod --build-artifacts=build.json
  else
    "$skaffold_bin" run -p news-chain
  fi
  kubectl rollout status deployment/news-chain -n apis --timeout=300s
  set_application_flag true
else
  gate_new_orders
  check_pending_orders
  for deployment in "${validator_workers[@]}"; do
    restart_and_wait "$deployment"
  done
  if kubectl get deployment/news-chain -n apis >/dev/null 2>&1; then
    kubectl scale deployment/news-chain --replicas=0 -n apis
  fi
  for node in "${chain_nodes[@]}"; do
    if kubectl get "statefulset/$node" -n blockchain >/dev/null 2>&1; then
      kubectl scale "statefulset/$node" --replicas=0 -n blockchain
    fi
  done
fi

echo "BLOCKCHAIN_ENABLED=${mode^^}; Kafka and LIGHT services remain running."
