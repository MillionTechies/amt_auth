#!/usr/bin/env bash
# Configure a local Keycloak 26 realm for amt-auth development.
#
# Keycloak must already be running:
#   KC_BOOTSTRAP_ADMIN_USERNAME=admin KC_BOOTSTRAP_ADMIN_PASSWORD=admin kc.sh start-dev
#
# Usage: KEYCLOAK_HOME=/path/to/keycloak scripts/keycloak-dev-setup.sh
# Dev-only credentials throughout. Do not use this against a real deployment.
set -euo pipefail

: "${KEYCLOAK_HOME:?Set KEYCLOAK_HOME to your Keycloak directory}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:8080}"
REALM="${REALM:-amilliontechies}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:5173}"

CONFIG="$(mktemp)"
trap 'rm -f "$CONFIG"' EXIT
kc() { local cmd=$1; shift; "$KEYCLOAK_HOME/bin/kcadm.sh" "$cmd" "$@" --config "$CONFIG"; }
id_of() { kc get "$1" -r "$REALM" --fields id,"$2" --format csv --noquotes | grep ",$3\$" | cut -d, -f1; }

kc config credentials --server "$KEYCLOAK_URL" --realm master \
  --user "${KC_ADMIN_USER:-admin}" --password "${KC_ADMIN_PASSWORD:-admin}"

# Realm, with organizations and admin events (the events feed the mirror webhook).
kc create realms -s realm="$REALM" -s enabled=true -s organizationsEnabled=true \
  -s adminEventsEnabled=true -s adminEventsDetailsEnabled=true
kc create roles -r "$REALM" -s name=admin  # platform admins

# The organization scope puts memberships in the token. By default it is a bare
# list of aliases; amt-auth needs the organization IDs and the user's groups.
org_scope="$(id_of client-scopes name organization)"
org_mapper="$(kc get "client-scopes/$org_scope/protocol-mappers/models" -r "$REALM" \
  --fields id --format csv --noquotes)"
kc update "client-scopes/$org_scope/protocol-mappers/models/$org_mapper" -r "$REALM" \
  -s 'config.addOrganizationId=true' -s 'config."jsonType.label"=JSON'
kc create "client-scopes/$org_scope/protocol-mappers/models" -r "$REALM" \
  -s name=organization-groups -s protocol=openid-connect \
  -s protocolMapper=oidc-organization-group-membership-mapper \
  -s 'config."access.token.claim"=true' -s 'config."id.token.claim"=true'

# Backend: confidential client whose service account calls the Admin API.
kc create clients -r "$REALM" -s clientId=amt-backend -s secret=dev-backend-secret \
  -s publicClient=false -s serviceAccountsEnabled=true -s standardFlowEnabled=false
backend="$(id_of clients clientId amt-backend)"
# Without the kc-admin-api scope the Admin API answers 401.
kc update "clients/$backend/default-client-scopes/$(id_of client-scopes name kc-admin-api)" -r "$REALM"
kc add-roles -r "$REALM" --uusername service-account-amt-backend --cclientid realm-management \
  --rolename manage-organizations --rolename view-organizations \
  --rolename manage-users --rolename view-users --rolename query-users --rolename query-groups

# Frontend: public client with PKCE. The audience mapper makes its tokens valid
# for the backend, which checks `aud` against AMT_CLIENT_ID.
kc create clients -r "$REALM" -s clientId=amt-frontend -s publicClient=true \
  -s standardFlowEnabled=true -s directAccessGrantsEnabled=true \
  -s "redirectUris=[\"$FRONTEND_URL/*\"]" -s "webOrigins=[\"$FRONTEND_URL\"]" \
  -s 'attributes."pkce.code.challenge.method"=S256' \
  -s "attributes.\"post.logout.redirect.uris\"=$FRONTEND_URL/*"
frontend="$(id_of clients clientId amt-frontend)"
kc create "clients/$frontend/protocol-mappers/models" -r "$REALM" \
  -s name=amt-backend-audience -s protocol=openid-connect -s protocolMapper=oidc-audience-mapper \
  -s 'config."included.client.audience"=amt-backend' -s 'config."access.token.claim"=true'

# Sample data: alice administers JKUAT and is in its Robotics Club.
kc create users -r "$REALM" -s username=alice -s email=alice@example.com \
  -s firstName=Alice -s lastName=Wanjiku -s enabled=true -s emailVerified=true
kc set-password -r "$REALM" --username alice --new-password alice
kc add-roles -r "$REALM" --uusername alice --rolename admin
alice="$(id_of users username alice)"
kc create organizations -r "$REALM" -s name=JKUAT -s alias=jkuat
org="$(id_of organizations alias jkuat)"
kc create "organizations/$org/members" -r "$REALM" -b "\"$alice\""
for name in admins clubs mentorships; do
  kc create "organizations/$org/groups" -r "$REALM" -s name="$name"
done
clubs="$(id_of "organizations/$org/groups" name clubs)"
admins="$(id_of "organizations/$org/groups" name admins)"
kc create "organizations/$org/groups/$clubs/children" -r "$REALM" -s 'name=Robotics Club'
robotics="$(id_of "organizations/$org/groups/$clubs/children" name 'Robotics Club')"
kc update "organizations/$org/groups/$admins/members/$alice" -r "$REALM"
kc update "organizations/$org/groups/$robotics/members/$alice" -r "$REALM"

echo
echo "Realm '$REALM' is ready. Sign in as alice / alice."
