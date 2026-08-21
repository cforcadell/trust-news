#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="infra"
DEPLOYMENT="keycloak"
REALM="TrustNews"
CLIENT_ID="TrustNewsWeb"
KEYCLOAK_URL="https://assermetry.com/auth"
FRONTEND_URL="https://assermetry.com"
KCADM="/opt/keycloak/bin/kcadm.sh"
REMOTE_CONFIG="/tmp/kcadm-reconcile-web-$$.config"

for command_name in kubectl python3; do
  command -v "$command_name" >/dev/null || {
    echo "ERROR: required command not found: $command_name" >&2
    exit 1
  }
done

cleanup() {
  kubectl exec -n "$NAMESPACE" "deployment/$DEPLOYMENT" -- \
    rm -f "$REMOTE_CONFIG" >/dev/null 2>&1 || true
}
trap cleanup EXIT

kubectl exec -i -n "$NAMESPACE" "deployment/$DEPLOYMENT" -- \
  sh -s -- "$KCADM" "$REMOTE_CONFIG" <<'KEYCLOAK_LOGIN'
set -eu

kcadm="$1"
config="$2"

test -x "$kcadm" || {
  echo "ERROR: kcadm is not available in the Keycloak container" >&2
  exit 1
}
: "${KEYCLOAK_ADMIN:?ERROR: KEYCLOAK_ADMIN is not configured}"
: "${KEYCLOAK_ADMIN_PASSWORD:?ERROR: KEYCLOAK_ADMIN_PASSWORD is not configured}"

"$kcadm" config credentials \
  --config "$config" \
  --server http://127.0.0.1:8080/auth \
  --realm master \
  --user "$KEYCLOAK_ADMIN" \
  --password "$KEYCLOAK_ADMIN_PASSWORD" \
  >/dev/null
KEYCLOAK_LOGIN

keycloak_admin() {
  kubectl exec -i -n "$NAMESPACE" "deployment/$DEPLOYMENT" -- \
    "$KCADM" "$@" --config "$REMOTE_CONFIG"
}

client_rows="$(keycloak_admin get clients \
  -r "$REALM" \
  -q "clientId=$CLIENT_ID" \
  --fields id \
  --format csv \
  --noquotes)"
client_ids=()
while IFS= read -r candidate_uuid; do
  [ -z "$candidate_uuid" ] || client_ids+=("$candidate_uuid")
done <<<"$client_rows"
if [ "${#client_ids[@]}" -ne 1 ]; then
  echo "ERROR: expected exactly one $CLIENT_ID client in realm $REALM; found ${#client_ids[@]}" >&2
  exit 1
fi
client_uuid="${client_ids[0]}"

realm_state="$(keycloak_admin get "realms/$REALM" --fields attributes)"
realm_attributes="$(printf '%s\n' "$realm_state" | python3 -c '
import json
import sys

frontend_url = sys.argv[1]
state = json.load(sys.stdin)
attributes = state.get("attributes")
if not isinstance(attributes, dict):
    attributes = {}
attributes["frontendUrl"] = frontend_url
json.dump(attributes, sys.stdout, separators=(",", ":"), sort_keys=True)
' "$KEYCLOAK_URL")"

client_state="$(keycloak_admin get "clients/$client_uuid" \
  -r "$REALM" \
  --fields attributes)"
client_attributes="$(printf '%s\n' "$client_state" | python3 -c '
import json
import sys

post_logout_redirect_uri = sys.argv[1]
state = json.load(sys.stdin)
attributes = state.get("attributes")
if not isinstance(attributes, dict):
    attributes = {}
attributes["post.logout.redirect.uris"] = post_logout_redirect_uri
json.dump(attributes, sys.stdout, separators=(",", ":"), sort_keys=True)
' "$FRONTEND_URL/*")"

# kcadm cannot reliably create a missing attributes map or address a map key
# containing dots through a nested -s path. Replace each complete map after
# merging the required value locally so existing attributes are preserved.
keycloak_admin update "realms/$REALM" \
  -s "attributes=$realm_attributes" \
  >/dev/null

keycloak_admin update "clients/$client_uuid" \
  -r "$REALM" \
  -s "rootUrl=$FRONTEND_URL" \
  -s "baseUrl=$FRONTEND_URL/" \
  -s "redirectUris=[\"$FRONTEND_URL/*\"]" \
  -s "webOrigins=[\"$FRONTEND_URL\"]" \
  -s "attributes=$client_attributes" \
  >/dev/null

realm_observed="$(keycloak_admin get "realms/$REALM" \
  --fields realm,attributes)"
client_observed="$(keycloak_admin get "clients/$client_uuid" \
  -r "$REALM" \
  --fields clientId,rootUrl,baseUrl,redirectUris,webOrigins,attributes)"

printf '{"realm":%s,"client":%s}\n' "$realm_observed" "$client_observed" | python3 -c '
import json
import sys

realm, client_id, keycloak_url, frontend_url = sys.argv[1:]
try:
    state = json.load(sys.stdin)
except (json.JSONDecodeError, TypeError) as error:
    print(f"ERROR: kcadm returned invalid JSON: {error}", file=sys.stderr)
    raise SystemExit(1)

realm_state = state.get("realm") or {}
client_state = state.get("client") or {}
realm_attributes = realm_state.get("attributes") or {}
client_attributes = client_state.get("attributes") or {}

observed = {
    "realm": realm_state.get("realm"),
    "realmFrontendUrl": realm_attributes.get("frontendUrl"),
    "clientId": client_state.get("clientId"),
    "rootUrl": client_state.get("rootUrl"),
    "baseUrl": client_state.get("baseUrl"),
    "redirectUris": client_state.get("redirectUris"),
    "webOrigins": client_state.get("webOrigins"),
    "postLogoutRedirectUris": client_attributes.get("post.logout.redirect.uris"),
}
expected = {
    "realm": realm,
    "realmFrontendUrl": keycloak_url,
    "clientId": client_id,
    "rootUrl": frontend_url,
    "baseUrl": f"{frontend_url}/",
    "redirectUris": [f"{frontend_url}/*"],
    "webOrigins": [frontend_url],
    "postLogoutRedirectUris": f"{frontend_url}/*",
}

if observed != expected:
    print("ERROR: Keycloak web alignment differs from the production contract", file=sys.stderr)
    print(f"expected={json.dumps(expected, sort_keys=True)}", file=sys.stderr)
    print(f"observed={json.dumps(observed, sort_keys=True)}", file=sys.stderr)
    raise SystemExit(1)

print(
    "keycloak_web_alignment=PASS "
    f"realm={realm} client={client_id} "
    f"keycloak_url={keycloak_url} frontend_url={frontend_url}"
)
' "$REALM" "$CLIENT_ID" "$KEYCLOAK_URL" "$FRONTEND_URL"
