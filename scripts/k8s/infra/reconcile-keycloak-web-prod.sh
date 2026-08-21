#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="infra"
DEPLOYMENT="keycloak"
REALM="TrustNews"
CLIENT_ID="TrustNewsWeb"
KEYCLOAK_URL="https://assermetry.com/auth"
FRONTEND_URL="https://assermetry.com"

for command_name in kubectl python3; do
  command -v "$command_name" >/dev/null || {
    echo "ERROR: required command not found: $command_name" >&2
    exit 1
  }
done

observed_state="$({
  kubectl exec -i -n "$NAMESPACE" "deployment/$DEPLOYMENT" -- \
    sh -s -- "$REALM" "$CLIENT_ID" "$KEYCLOAK_URL" "$FRONTEND_URL" <<'KEYCLOAK_SCRIPT'
set -eu

realm="$1"
client_id="$2"
keycloak_url="$3"
frontend_url="$4"
kcadm=/opt/keycloak/bin/kcadm.sh
config="/tmp/kcadm-reconcile-web-$$.config"
trap 'rm -f "$config"' EXIT

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

client_rows="$("$kcadm" get clients \
  --config "$config" \
  -r "$realm" \
  -q "clientId=$client_id" \
  --fields id \
  --format csv \
  --noquotes)"
set -- $client_rows
if [ "$#" -ne 1 ]; then
  echo "ERROR: expected exactly one $client_id client in realm $realm; found $#" >&2
  exit 1
fi
client_uuid="$1"

"$kcadm" update "realms/$realm" \
  --config "$config" \
  -s "attributes.frontendUrl=$keycloak_url" \
  >/dev/null

"$kcadm" update "clients/$client_uuid" \
  --config "$config" \
  -r "$realm" \
  -s "rootUrl=$frontend_url" \
  -s "baseUrl=$frontend_url/" \
  -s "redirectUris=[\"$frontend_url/*\"]" \
  -s "webOrigins=[\"$frontend_url\"]" \
  -s "attributes.\"post.logout.redirect.uris\"=\"$frontend_url/*\"" \
  >/dev/null

printf '{"realm":'
"$kcadm" get "realms/$realm" \
  --config "$config" \
  --fields realm,attributes
printf ',"client":'
"$kcadm" get "clients/$client_uuid" \
  --config "$config" \
  -r "$realm" \
  --fields clientId,rootUrl,baseUrl,redirectUris,webOrigins,attributes
printf '}\n'
KEYCLOAK_SCRIPT
} 2> >(cat >&2))"

printf '%s\n' "$observed_state" | python3 -c '
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
