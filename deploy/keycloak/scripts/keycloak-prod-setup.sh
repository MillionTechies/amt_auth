#!/usr/bin/env bash
# Set up (or bring up to date) the production realm and one pair of clients per
# product. Safe to run again: everything is created if missing, updated if not.
#
# Inside the Keycloak container:
#   docker compose exec -T \
#     -e PRODUCTS="community=https://community.amilliontechies.com" \
#     amt-keycloak bash /opt/keycloak/amt-scripts/keycloak-prod-setup.sh
#
# PRODUCTS is a space-separated list of name=URL[,URL...]. Each product gets:
#   <name>-frontend  public client (PKCE), sign-in only from its URLs
#   <name>-backend   confidential client whose service account calls the Admin API
# The first URL is the product's site. Any others are extra places its web app
# may sign in from, such as developers' machines:
#   community=https://community.amilliontechies.com,http://localhost:5173
# A backend's secret is printed once, when the client is created. To read it
# again: Clients > <name>-backend > Credentials in the admin console.
#
# No users are created. Configure email with keycloak-email.sh and Google with
# keycloak-google.sh afterwards.
#
# HIDE_SECRETS=1 leaves new secrets out of the output (deploy.sh sets it when its
# output goes to a log, such as GitHub Actions).
set -euo pipefail

: "${PRODUCTS:?Set PRODUCTS, e.g. PRODUCTS=\"community=https://community.amilliontechies.com\"}"
KEYCLOAK_HOME="${KEYCLOAK_HOME:-/opt/keycloak}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:8080}"
REALM="${REALM:-amilliontechies}"
SCRIPTS="$(dirname "$0")"

CONFIG="$(mktemp)"
trap 'rm -f "$CONFIG"' EXIT
kc() { local cmd=$1; shift; "$KEYCLOAK_HOME/bin/kcadm.sh" "$cmd" "$@" --config "$CONFIG"; }
csv() { kc get "$@" --format csv --noquotes; }
client_id_of() { csv clients -r "$REALM" -q clientId="$1" --fields id,clientId | grep ",$1\$" | cut -d, -f1 || true; }
has_mapper() { csv "$1/protocol-mappers/models" -r "$REALM" --fields name | grep -qx "$2"; }

# shellcheck source=kc-login.sh
. "$(dirname "$0")/kc-login.sh"

# --- Realm -----------------------------------------------------------------------

if ! kc get "realms/$REALM" --fields realm >/dev/null 2>&1; then
  kc create realms -s realm="$REALM" -s enabled=true
  echo "Created realm '$REALM'."
fi

# Organizations; admin events (what changed in organizations); the login event
# log (who signed up and signed in), kept for 30 days; passkeys.
kc update "realms/$REALM" \
  -s organizationsEnabled=true \
  -s adminEventsEnabled=true -s adminEventsDetailsEnabled=true \
  -s eventsEnabled=true -s eventsExpiration=2592000 \
  -s 'enabledEventTypes=["REGISTER","LOGIN","LOGIN_ERROR","VERIFY_EMAIL","UPDATE_PASSWORD"]' \
  -s webAuthnPolicyPasswordlessPasskeysEnabled=true

csv roles -r "$REALM" --fields name | grep -qx admin \
  || kc create roles -r "$REALM" -s name=admin  # platform admins

# The organization scope puts memberships in the token. By default it is a bare
# list of aliases; amt-auth needs the organization IDs and the user's groups.
org_scope="$(csv client-scopes -r "$REALM" --fields id,name | grep ',organization$' | cut -d, -f1)"
org_scope_path="client-scopes/$org_scope"
org_mapper="$(csv "$org_scope_path/protocol-mappers/models" -r "$REALM" --fields id,protocolMapper \
  | grep ',oidc-organization-membership-mapper$' | cut -d, -f1)"
kc update "$org_scope_path/protocol-mappers/models/$org_mapper" -r "$REALM" \
  -s 'config.addOrganizationId=true' -s 'config."jsonType.label"=JSON'
has_mapper "$org_scope_path" organization-groups \
  || kc create "$org_scope_path/protocol-mappers/models" -r "$REALM" \
    -s name=organization-groups -s protocol=openid-connect \
    -s protocolMapper=oidc-organization-group-membership-mapper \
    -s 'config."access.token.claim"=true' -s 'config."id.token.claim"=true'

admin_api_scope="$(csv client-scopes -r "$REALM" --fields id,name | grep ',kc-admin-api$' | cut -d, -f1)"

# --- Clients, one pair per product -----------------------------------------------

# upsert_client <clientId> <kcadm -s settings...>: prints the client's internal id.
upsert_client() {
  local client=$1; shift
  local id
  id="$(client_id_of "$client")"
  if [ -n "$id" ]; then
    kc update "clients/$id" -r "$REALM" "$@"
  else
    kc create clients -r "$REALM" -s clientId="$client" "$@" >/dev/null 2>&1
    id="$(client_id_of "$client")"
    echo "Created client '$client'." >&2
  fi
  echo "$id"
}

# Check every product before changing anything: a mistyped entry stops the setup
# (and a deploy), rather than leaving that product's clients quietly out of date.
invalid=0
for product in $PRODUCTS; do
  IFS=, read -r -a sites <<<"${product#*=}"
  [[ "${product%%=*}" != "$product" ]] || invalid=1
  for site in "${sites[@]%/}"; do
    [[ "$site" =~ ^https?://[^/*\"\']+$ ]] || invalid=1
  done
  [ "$invalid" = 0 ] || { echo "Invalid product '$product': expected name=https://host[,http://host:port] (no path, no wildcard, no quotes)." >&2; exit 1; }
done

for product in $PRODUCTS; do
  name="${product%%=*}"
  IFS=, read -r -a sites <<<"${product#*=}"
  sites=("${sites[@]%/}")
  url="${sites[0]}"
  redirects="$(printf '"%s/*",' "${sites[@]}")"
  origins="$(printf '"%s",' "${sites[@]}")"
  logouts="$(printf '%s/*##' "${sites[@]}")"

  # Backend: no browser sign-in, only its own service account.
  backend_created=0
  [ -n "$(client_id_of "$name-backend")" ] || backend_created=1
  backend="$(upsert_client "$name-backend" \
    -s publicClient=false -s serviceAccountsEnabled=true \
    -s standardFlowEnabled=false -s directAccessGrantsEnabled=false \
    -s implicitFlowEnabled=false)"
  # Without the kc-admin-api scope the Admin API answers 401.
  kc update "clients/$backend/default-client-scopes/$admin_api_scope" -r "$REALM"
  kc add-roles -r "$REALM" --uusername "service-account-$name-backend" --cclientid realm-management \
    --rolename manage-organizations --rolename view-organizations \
    --rolename manage-users --rolename view-users --rolename query-users --rolename query-groups

  # Frontend: public client with PKCE, allowed to redirect back to its own URLs only.
  frontend="$(upsert_client "$name-frontend" \
    -s publicClient=true -s standardFlowEnabled=true \
    -s directAccessGrantsEnabled=false -s implicitFlowEnabled=false \
    -s "rootUrl=$url" -s "baseUrl=$url/" \
    -s "redirectUris=[${redirects%,}]" -s "webOrigins=[${origins%,}]" \
    -s 'attributes."pkce.code.challenge.method"=S256' \
    -s "attributes.\"post.logout.redirect.uris\"=${logouts%##}")"
  # Its tokens must be valid for its backend, which checks `aud` against AMT_CLIENT_ID.
  has_mapper "clients/$frontend" "$name-backend-audience" \
    || kc create "clients/$frontend/protocol-mappers/models" -r "$REALM" \
      -s name="$name-backend-audience" -s protocol=openid-connect -s protocolMapper=oidc-audience-mapper \
      -s "config.\"included.client.audience\"=$name-backend" -s 'config."access.token.claim"=true'

  echo "Product '$name': $name-frontend signs in from ${sites[*]}, $name-backend calls the Admin API."
  if [ "$backend_created" = 1 ]; then
    echo "  AMT_CLIENT_ID=$name-backend"
    if [ "${HIDE_SECRETS:-}" = 1 ]; then
      echo "  AMT_CLIENT_SECRET: read it in the admin console, Clients > $name-backend > Credentials"
    else
      secret="$(kc get "clients/$backend/client-secret" -r "$REALM" --fields value --format csv --noquotes)"
      echo "  AMT_CLIENT_SECRET=$secret   (shown once; store it in $name's backend env)"
    fi
  fi
done

# --- Sign-up, theme, brute-force protection, password policy ----------------------

CLIENT_ID='' VERIFY_EMAIL=true bash "$SCRIPTS/keycloak-realm-settings.sh"

# --- Admin realm (master) ---------------------------------------------------------
#
# The admin console is served on its own hostname (KC_HOSTNAME_ADMIN). Its sign-in
# uses the same theme, and the realm's URLs point at that hostname; otherwise the
# console's login check goes to the public host, where /realms/master is blocked,
# and stops with "Timeout when waiting for 3rd party check iframe message".
ADMIN_URL="${KC_HOSTNAME_ADMIN:-http://localhost:8080}"
kc update realms/master -s loginTheme=amt -s "attributes.frontendUrl=$ADMIN_URL" \
  -s bruteForceProtected=true -s permanentLockout=false -s failureFactor=5 \
  -s 'passwordPolicy=length(12) and notUsername and notEmail'
# A new frontend URL changes the master realm's token issuer, so sign in again.
. "$SCRIPTS/kc-login.sh"

# Every admin signs in with a password and a code from an authenticator app. New
# admins set the app up on their first sign-in; existing ones without it are asked
# to on their next. The account this script signs in with is left alone, because
# kcadm can't type a code: that is the bootstrap admin, which you delete.
kc update authentication/required-actions/CONFIGURE_TOTP -r master -s enabled=true -s defaultAction=true
self="${KC_ADMIN_USER:-${KC_BOOTSTRAP_ADMIN_USERNAME:-admin}}"
csv users -r master --fields id,username | while IFS=, read -r uid uname; do
  case "$uname" in service-account-*) continue ;; esac
  [ -z "${KC_ADMIN_CLIENT_SECRET:-}" ] && [ "$uname" = "$self" ] && continue
  csv "users/$uid/credentials" -r master --fields type | grep -qx otp && continue
  actions="$(kc get "users/$uid" -r master --fields requiredActions --format json | tr -d ' \n')"
  case "$actions" in *CONFIGURE_TOTP*) continue ;; esac
  actions="${actions#*[}"; actions="${actions%]*}"
  kc update "users/$uid" -r master -s "requiredActions=[${actions:+$actions,}\"CONFIGURE_TOTP\"]"
  echo "Admin '$uname' must set up an authenticator app on their next sign-in."
done

# amt-deploy: the service account deploy.sh and these scripts sign in with
# (KC_ADMIN_CLIENT_SECRET). It has no password or browser sign-in, so no code either.
deploy_id="$(csv clients -r master -q clientId=amt-deploy --fields id,clientId | grep ',amt-deploy$' | cut -d, -f1 || true)"
if [ -z "$deploy_id" ]; then
  kc create clients -r master -s clientId=amt-deploy -s publicClient=false \
    -s serviceAccountsEnabled=true -s standardFlowEnabled=false \
    -s directAccessGrantsEnabled=false -s implicitFlowEnabled=false >/dev/null
  deploy_id="$(csv clients -r master -q clientId=amt-deploy --fields id,clientId | grep ',amt-deploy$' | cut -d, -f1)"
  kc add-roles -r master --uusername service-account-amt-deploy --rolename admin
  # Without the kc-admin-api scope the Admin API answers 401.
  kc update "clients/$deploy_id/default-client-scopes/$(csv client-scopes -r master --fields id,name | grep ',kc-admin-api$' | cut -d, -f1)" -r master
  echo "Created the amt-deploy service account. Put its secret in the server's .env:"
  if [ "${HIDE_SECRETS:-}" = 1 ]; then
    echo "  KC_ADMIN_CLIENT_SECRET: read it in the admin console, master > Clients > amt-deploy > Credentials"
  else
    echo "  KC_ADMIN_CLIENT_SECRET=$(kc get "clients/$deploy_id/client-secret" -r master --fields value --format csv --noquotes)   (shown once)"
  fi
fi

echo
echo "Realm '$REALM' is ready at its issuer: \$KC_HOSTNAME/realms/$REALM"
