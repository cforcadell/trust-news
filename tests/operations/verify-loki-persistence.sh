#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="infra"
PROBE_ID="observability-persistence-probe-20260817T1605Z"
EXPECTED_STORAGE_CLASS="local-path"
EXECUTE=false

usage() {
  cat <<'EOF'
Usage: verify-loki-persistence.sh --execute [--probe-id ID] [--namespace NAME]

Generates one request through the local Traefik origin, confirms that Loki has
ingested it, restarts Loki, and confirms that the same event is still present.
The script only prints status codes and event counts; it never prints raw logs.

Safety gates:
  --execute is mandatory.
  loki-data must be Bound, request 5Gi, and use the local-path StorageClass.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --execute) EXECUTE=true; shift ;;
    --probe-id) PROBE_ID="$2"; shift 2 ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$EXECUTE" != true ]]; then
  echo "ERROR: --execute is required because this check restarts Loki" >&2
  exit 2
fi

case "$PROBE_ID" in
  *[!a-zA-Z0-9._-]*|'')
    echo "ERROR: probe ID may only contain letters, digits, dots, underscores and hyphens" >&2
    exit 2
    ;;
esac

for command_name in kubectl curl python3; do
  command -v "$command_name" >/dev/null || {
    echo "ERROR: required command not found: $command_name" >&2
    exit 1
  }
done

pvc_phase="$(kubectl get pvc loki-data -n "$NAMESPACE" -o jsonpath='{.status.phase}')"
pvc_size="$(kubectl get pvc loki-data -n "$NAMESPACE" -o jsonpath='{.spec.resources.requests.storage}')"
pvc_class="$(kubectl get pvc loki-data -n "$NAMESPACE" -o jsonpath='{.spec.storageClassName}')"
mount_path="$(kubectl get deployment loki -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[?(@.name=="loki")].volumeMounts[?(@.name=="loki-data")].mountPath}')"

if [[ "$pvc_phase" != "Bound" || "$pvc_size" != "5Gi" || "$pvc_class" != "$EXPECTED_STORAGE_CLASS" ]]; then
  echo "ERROR: production safety gate failed for loki-data (phase=$pvc_phase size=$pvc_size class=$pvc_class)" >&2
  exit 1
fi
if [[ "$mount_path" != "/loki" ]]; then
  echo "ERROR: loki-data is mounted at '$mount_path', expected /loki" >&2
  exit 1
fi

kubectl rollout status deployment/loki -n "$NAMESPACE" --timeout=180s >/dev/null

current_loki_pod() {
  kubectl get pods -n "$NAMESPACE" -l app=loki -o json | python3 -c '
import json, sys
pods = json.load(sys.stdin).get("items", [])
candidates = []
for pod in pods:
    if pod.get("metadata", {}).get("deletionTimestamp"):
        continue
    statuses = pod.get("status", {}).get("containerStatuses", [])
    if statuses and all(item.get("ready") for item in statuses):
        candidates.append(pod)
if len(candidates) != 1:
    raise SystemExit(f"Expected exactly one non-terminating Ready Loki pod, found {len(candidates)}")
metadata = candidates[0]["metadata"]
print(metadata["name"], metadata["uid"])
'
}

read -r before_name before_uid < <(current_loki_pod)
start_ns="$(( $(date -u +%s) - 300 ))000000000"

http_status="$(curl --silent --show-error --insecure \
  --resolve 'assermetry.com:443:127.0.0.1' \
  --output /dev/null --write-out '%{http_code}' \
  "https://assermetry.com/$PROBE_ID")"
echo "probe_generated=true http_status=$http_status"

query_count() {
  local end_ns query encoded path
  end_ns="$(date -u +%s)000000000"
  query="{namespace=\"kube-system\", container=\"traefik\"} |= \"/$PROBE_ID\""
  encoded="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$query")"
  path="/api/v1/namespaces/$NAMESPACE/services/http:loki:3100/proxy/loki/api/v1/query_range?query=$encoded&start=$start_ns&end=$end_ns&limit=100"
  kubectl get --raw "$path" | python3 -c '
import json, sys
payload = json.load(sys.stdin)
if payload.get("status") != "success":
    raise SystemExit("Loki query did not return success")
print(sum(len(stream.get("values", [])) for stream in payload.get("data", {}).get("result", [])))
'
}

before_count=0
for _attempt in 1 2 3 4 5 6; do
  before_count="$(query_count)"
  [[ "$before_count" -gt 0 ]] && break
  sleep 5
done
if [[ "$before_count" -eq 0 ]]; then
  echo "ERROR: probe was not found in Loki before restart" >&2
  exit 1
fi
echo "probe_before_restart=$before_count"

kubectl rollout restart deployment/loki -n "$NAMESPACE" >/dev/null
kubectl rollout status deployment/loki -n "$NAMESPACE" --timeout=180s >/dev/null
read -r after_name after_uid < <(current_loki_pod)
if [[ "$after_uid" == "$before_uid" ]]; then
  echo "ERROR: Loki pod UID did not change after restart" >&2
  exit 1
fi

after_count=0
for _attempt in 1 2 3 4 5 6; do
  after_count="$(query_count)"
  [[ "$after_count" -gt 0 ]] && break
  sleep 5
done
if [[ "$after_count" -eq 0 ]]; then
  echo "ERROR: probe was not retained after the Loki restart" >&2
  exit 1
fi

restart_count="$(kubectl get pod "$after_name" -n "$NAMESPACE" -o jsonpath='{.status.containerStatuses[?(@.name=="loki")].restartCount}')"
ready="$(kubectl get pod "$after_name" -n "$NAMESPACE" -o jsonpath='{.status.containerStatuses[?(@.name=="loki")].ready}')"
echo "probe_after_restart=$after_count pod_replaced=true ready=$ready container_restarts=$restart_count"
echo "loki_persistence=PASS"
