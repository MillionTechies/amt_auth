# Frontend

The Vite + React frontend for amt-auth. It signs in with Keycloak and talks to the small Django backend in `backend/`, which validates the token with `amt_auth.django`.

```
frontend/   Vite + React + react-oidc-context
backend/    Django + DRF, mounts amt_auth.django
```

## Run it

You need Keycloak 26 running locally, with the realm configured by the setup script:

```bash
KC_BOOTSTRAP_ADMIN_USERNAME=admin KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
  $KEYCLOAK_HOME/bin/kc.sh start-dev

KEYCLOAK_HOME=/path/to/keycloak scripts/keycloak-dev-setup.sh
```

The script creates the `amilliontechies` realm, the `amt-backend` and `amt-frontend` clients, and a sample user `alice` / `alice` who administers the JKUAT organization. The values in both `.env.example` files match it.

Backend, from the repo root:

```bash
pip install -e ".[dev]"
cd backend
cp .env.example .env        # fill in the values
set -a && source .env && set +a
python manage.py migrate
python manage.py runserver
```

Frontend:

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev                 # http://localhost:5173, proxies /api to :8000
```

## What it shows

- Sign in and out through Keycloak; the access token is refreshed automatically.
- `GET /api/me/` returns the user and their organizations straight from the token.
- An organization admin sees an invite form (`POST /api/auth/organizations/<id>/invitations/`).
- A realm admin sees a "New organization" form (`POST /api/auth/organizations/`).
