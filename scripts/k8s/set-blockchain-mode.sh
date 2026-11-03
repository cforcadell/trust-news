#!/usr/bin/env bash
set -euo pipefail

# Run after the core infrastructure and API manifests have been applied.
# BLOCKCHAIN_ENABLED=ON|OFF is the single deployment switch.
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
skaffold_bin=

mode="${BLOCKCHAIN_ENABLED:-OFF}"
case "${mode^^}" in
  ON|TRUE|1) enabled=true ;;
  OFF|FALSE|0) enabled=false ;;
  *) echo "BLOCKCHAIN_ENABLED must be ON or OFF" >&2; exit 2 ;;
esac

chain_nodes=(geth-bootnode geth-miner geth-rpc-endpoint)
validator_workers=(validate-worker-1 validate-worker-2 validate-worker-3)

resolve_skaffold() {
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
}

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

prepare_off_rollout() {
  set_mode_config false
  echo "Prepared BLOCKCHAIN_ENABLED=false for the next rollout; running deployments were not restarted."
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
  echo "Pending blockchain orders: $pending"
  if [ "$pending" -gt 0 ]; then
    echo "Cannot disable blockchain: $pending orders are still in progress." >&2
    exit 1
  fi
}

cancel_pending_orders() {
  case "${CANCEL_PENDING_CONFIRMED:-}" in
    true|TRUE|1) ;;
    *)
      echo "Set CANCEL_PENDING_CONFIRMED=true to cancel in-progress blockchain orders." >&2
      exit 2
      ;;
  esac

  local reason cancelled
  reason="${CANCEL_PENDING_REASON:-Blockchain runtime disabled during deployment transition}"
  cancelled="$(kubectl exec -i -n apis deployment/news-handler -- \
    env "CANCEL_PENDING_REASON=$reason" python - <<'PY'
import asyncio
import os
import sys
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient
from common.utils.mongo import build_mongo_uri_from_env

PENDING_STATUSES = [
    "CREATED", "ASSERTIONS_REQUESTED", "DOCUMENT_CREATED", "IPFS_PENDING",
    "IPFS_UPLOADED", "BLOCKCHAIN_REQUESTED", "BLOCKCHAIN_PENDING",
    "VALIDATION_PENDING",
]

async def main():
    client = AsyncIOMotorClient(build_mongo_uri_from_env(), serverSelectionTimeoutMS=5000)
    collection = client[os.getenv("MONGO_DBNAME", "newsdb")][os.getenv("MONGO_COLLECTION", "news")]
    query = {
        "$or": [{"validation_mode": "BLOCKCHAIN"}, {"validation_mode": {"$exists": False}}],
        "status": {"$in": PENDING_STATUSES},
    }
    documents = await collection.find(
        query,
        {"_id": 1, "order_id": 1, "status": 1, "validators_pending": 1},
    ).to_list(length=None)
    cancelled = 0
    now = datetime.now(timezone.utc).isoformat()
    reason = os.environ["CANCEL_PENDING_REASON"]
    for document in documents:
        previous_status = document.get("status")
        result = await collection.update_one(
            {"_id": document["_id"], "status": previous_status},
            {"$set": {
                "status": "FAILED",
                "validators_pending": 0,
                "updated_at": now,
                "cancellation": {
                    "code": "BLOCKCHAIN_DISABLED_BY_OPERATOR",
                    "reason": reason,
                    "previous_status": previous_status,
                    "previous_validators_pending": document.get("validators_pending"),
                    "cancelled_at": now,
                },
            }},
        )
        if result.modified_count == 1:
            cancelled += 1
            print(
                f"Cancelled order {document.get('order_id', '<missing>')} "
                f"from status {previous_status}",
                file=sys.stderr,
            )
    print(cancelled)
    client.close()

asyncio.run(main())
PY
)"
  if ! [[ "$cancelled" =~ ^[0-9]+$ ]]; then
    echo "Could not read cancelled blockchain order count: $cancelled" >&2
    exit 1
  fi
  echo "Cancelled $cancelled in-progress blockchain order(s)."
}

scale_chain_runtime_to_zero() {
  if kubectl get deployment/news-chain -n apis >/dev/null 2>&1; then
    kubectl scale deployment/news-chain --replicas=0 -n apis
  fi
  for node in "${chain_nodes[@]}"; do
    if kubectl get "statefulset/$node" -n blockchain >/dev/null 2>&1; then
      kubectl scale "statefulset/$node" --replicas=0 -n blockchain
    fi
  done
}

stop_chain_runtime_before_rollout() {
  case "${MAINTENANCE_LOCK_CONFIRMED:-}" in
    true|TRUE|1) ;;
    *)
      echo "Set MAINTENANCE_LOCK_CONFIRMED=true after verifying the external maintenance lock." >&2
      exit 2
      ;;
  esac
  check_pending_orders
  scale_chain_runtime_to_zero
  echo "Blockchain runtime stopped; PVCs, Kafka and LIGHT services were preserved."
}

cancel_pending_and_stop_chain_runtime() {
  case "${MAINTENANCE_LOCK_CONFIRMED:-}" in
    true|TRUE|1) ;;
    *)
      echo "Set MAINTENANCE_LOCK_CONFIRMED=true after verifying the external maintenance lock." >&2
      exit 2
      ;;
  esac
  cancel_pending_orders
  check_pending_orders
  scale_chain_runtime_to_zero
  check_pending_orders
  echo "Pending blockchain orders were cancelled and the blockchain runtime was stopped."
}

case "${1:-}" in
  --check-pending)
    check_pending_orders
    exit 0
    ;;
  --prepare-off)
    prepare_off_rollout
    exit 0
    ;;
  --gate)
    gate_new_orders
    exit 0
    ;;
  --stop-chain-runtime)
    stop_chain_runtime_before_rollout
    exit 0
    ;;
  --cancel-pending-and-stop-chain)
    cancel_pending_and_stop_chain_runtime
    exit 0
    ;;
  "") ;;
  *)
    echo "Unknown action: $1" >&2
    echo "Usage: $0 [--check-pending|--prepare-off|--gate|--stop-chain-runtime|--cancel-pending-and-stop-chain]" >&2
    exit 2
    ;;
esac

set_application_flag() {
  local value="$1"
  set_mode_config "$value"
  for deployment in news-handler "${validator_workers[@]}" gateway; do
    restart_and_wait "$deployment"
  done
}

if [ "$enabled" = true ]; then
  resolve_skaffold
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
  scale_chain_runtime_to_zero
fi

echo "BLOCKCHAIN_ENABLED=${mode^^}; Kafka and LIGHT services remain running."
