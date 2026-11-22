#!/usr/bin/env bash
# Bring the server up to date with GitHub. Run it on the server after merging:
#   /var/www/projects/amt-auth/deploy/keycloak/deploy.sh
#
# 1. git pull (fast-forward only), then restarts itself so the new copy of this
#    script is the one that runs
# 2. backs up the database (backup.sh), if Keycloak is already running
# 3. builds the image from this checkout, tagged as KEYCLOAK_IMAGE in .env
# 4. docker compose up -d, and waits until Keycloak is healthy
# 5. reruns the realm setup (keycloak-prod-setup.sh) for PRODUCTS in .env,
#    signing in with the amt-deploy service account (KC_ADMIN_CLIENT_SECRET), or
#    the bootstrap admin on a fresh server
# 6. checks the public URL
#
# Options: --no-pull, --no-backup, --no-setup.
#
# GitHub Actions runs this after every merge to develop
# (.github/workflows/deploy-keycloak.yml), over an SSH key that can run nothing
# else. When the output isn't a terminal, new secrets are left out of it. When
# GitHub runs it (SSH_ORIGINAL_COMMAND is set), a skipped realm setup is an error,
# and it ends with a `client:` line per product that the workflow checks from outside.
set -euo pipefail

cd "$(dirname "$0")"

PULL=1 BACKUP=1 SETUP=1
for arg in "$@"; do
  case "$arg" in
    --no-pull) PULL=0 ;;
    --no-backup) BACKUP=0 ;;
    --no-setup) SETUP=0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

step() { printf '\n==> %s\n' "$*"; }
# The last NAME=value line in .env, without the quotes around the value if it has them.
env_value() {
  local value
  value="$(grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- || true)"
  value="${value%\"}"; value="${value#\"}"
  value="${value%\'}"; value="${value#\'}"
  echo "$value"
}

[ -f .env ] || { echo ".env is missing: cp .env.example .env and fill it in." >&2; exit 1; }

# --- 1. Pull -----------------------------------------------------------------------
# Pulling can change this very file while bash is reading it, so pull first and
# then start again from the fresh copy.
if [ "$PULL" = 1 ] && [ -z "${AMT_DEPLOY_PULLED:-}" ]; then
  step "Pulling $(git rev-parse --abbrev-ref HEAD) from GitHub"
  git pull --ff-only
  AMT_DEPLOY_PULLED=1 exec bash "$PWD/$(basename "$0")" "$@"
fi
echo "Deploying $(git log -1 --format='%h %s')"

IMAGE="$(env_value KEYCLOAK_IMAGE)"
IMAGE="${IMAGE:-ghcr.io/milliontechies/amt-keycloak:26.8.2-1}"
HOSTNAME_URL="$(env_value KC_HOSTNAME)"
HOSTNAME_URL="${HOSTNAME_URL:-https://auth.amilliontechies.com}"

# --- 2. Backup ---------------------------------------------------------------------
if [ "$BACKUP" = 1 ] && [ -n "$(docker compose ps -q amt-keycloak-db 2>/dev/null)" ]; then
  step "Backing up the database"
  ./backup.sh
fi

# --- 3. Build ----------------------------------------------------------------------
step "Building $IMAGE"
docker build -t "$IMAGE" .

# --- 4. Start ----------------------------------------------------------------------
step "Starting Keycloak"
docker compose up -d

printf 'Waiting for Keycloak to be healthy'
for _ in $(seq 1 60); do
  status="$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q amt-keycloak)" 2>/dev/null || true)"
  [ "$status" = healthy ] && break
  printf '.'
  sleep 5
done
echo
if [ "$status" != healthy ]; then
  echo "Keycloak is not healthy after 5 minutes. Logs: docker compose logs amt-keycloak --tail 100" >&2
  exit 1
fi
echo "Keycloak is healthy."

# --- 5. Realm setup ----------------------------------------------------------------
PRODUCTS="$(env_value PRODUCTS)"
CLIENT_SECRET="$(env_value KC_ADMIN_CLIENT_SECRET)"
skip=""
if [ "$SETUP" = 0 ]; then
  :
elif [ -z "$PRODUCTS" ]; then
  skip="set PRODUCTS in .env to run it on every deploy."
elif [ -z "$CLIENT_SECRET" ] && [ -z "$(env_value KC_BOOTSTRAP_ADMIN_USERNAME)" ]; then
  skip="set KC_ADMIN_CLIENT_SECRET in .env (the amt-deploy secret)."
fi
if [ -n "$skip" ]; then
  # By hand that's a warning; from GitHub it fails the run, or the clients could
  # quietly stay out of date behind a green deploy.
  if [ -n "${SSH_ORIGINAL_COMMAND:-}" ]; then
    echo "The realm setup can't run: $skip" >&2
    exit 1
  fi
  echo "Skipping the realm setup: $skip"
elif [ "$SETUP" = 1 ]; then
  step "Updating the realm and clients"
  # Keycloak reports healthy a little before its Admin API stops answering 503,
  # so give the setup a few tries. It is safe to run again.
  hide=0
  [ -t 1 ] || hide=1
  for attempt in 1 2 3 4 5; do
    if docker compose exec -T -e "PRODUCTS=$PRODUCTS" -e "KC_ADMIN_CLIENT_SECRET=$CLIENT_SECRET" -e "HIDE_SECRETS=$hide" \
      amt-keycloak bash /opt/keycloak/amt-scripts/keycloak-prod-setup.sh; then
      break
    fi
    if [ "$attempt" = 5 ]; then
      echo "The realm setup failed 5 times. Logs: docker compose logs amt-keycloak --tail 100" >&2
      exit 1
    fi
    echo "Retrying in 15 seconds..."
    sleep 15
  done
fi

# --- 6. Check ----------------------------------------------------------------------
step "Checking $HOSTNAME_URL"
issuer="$(curl -fsS "$HOSTNAME_URL/realms/amilliontechies/.well-known/openid-configuration" | grep -o '"issuer":"[^"]*"' || true)"
admin_code="$(curl -s -o /dev/null -w '%{http_code}' "$HOSTNAME_URL/admin/")"
echo "issuer:  ${issuer:-MISSING}"
echo "/admin/: $admin_code (expected 404: the console is on KC_HOSTNAME_ADMIN)"
if [ -z "$issuer" ] || [ "$admin_code" != 404 ]; then
  echo "Check failed." >&2
  exit 1
fi

# One line per product for the workflow: the frontend client and every URL it
# should sign in from.
for product in $PRODUCTS; do
  echo "client: ${product%%=*}-frontend ${product#*=}" | tr , ' '
done

echo
echo "Done: $(git log -1 --format='%h %s')"
