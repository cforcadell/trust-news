#!/usr/bin/env bash
# Reads the database name embedded in a gzip-compressed pg_dump custom archive.
# pg_restore runs in the selected pod, so no PostgreSQL client is needed locally.

postgresql_select_pod() {
  local namespace=$1 selector=$2 requested=$3 pods
  local -a matches=()
  if [[ -n $requested ]]; then
    postgresql_pod=$requested
  else
    pods=$(kubectl get pods -n "$namespace" -l "$selector" \
      -o jsonpath='{range .items[*]}{.metadata.name}{" "}{end}')
    read -r -a matches <<< "$pods" || true
    [[ ${#matches[@]} -eq 1 ]] || {
      echo "Expected one PostgreSQL pod in $namespace for selector $selector; use --pod" >&2
      return 1
    }
    postgresql_pod=${matches[0]}
  fi
  kubectl wait -n "$namespace" --for=condition=Ready "pod/$postgresql_pod" --timeout=180s >/dev/null
}

postgresql_pod_database() {
  local namespace=$1 pod=$2 container=$3
  kubectl exec -n "$namespace" "$pod" -c "$container" -- sh -ec \
    'printf %s "${POSTGRES_DB:?POSTGRES_DB is unset}"'
}

postgresql_archive_database() {
  local archive=$1 namespace=$2 pod=$3 container=$4
  gzip -dc "$archive" | \
    kubectl exec -i -n "$namespace" "$pod" -c "$container" -- pg_restore -l | \
    awk '/^;[[:space:]]*dbname: / && !found {
      sub(/^;[[:space:]]*dbname: /, "")
      print
      found=1
    }
    END { if (!found) exit 1 }'
}
