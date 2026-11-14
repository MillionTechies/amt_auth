# amt-auth

Python authentication library for the A Million Techies ecosystem. Wraps Keycloak 26+ to validate JWTs, resolve organization and group context from token claims, and sync org membership events into a local mirror.

Every Django backend in the platform imports this library — the core has zero Django dependencies.

## Installation

```bash
# Core only (JWT validation + sync)
pip install amt-auth

# With Django REST Framework integration
pip install "amt-auth[django]"
```

## Quick start

```python
from amt_auth import AuthService, load_config

config = load_config()          # reads env vars; raises ConfigError on bad config
service = AuthService(config)

# Validate a Bearer token from a request header
claims = service.validate_token(raw_jwt)

print(claims.sub)               # Keycloak user ID
print(claims.email)             # alice@example.com
print(claims.realm_roles)       # frozenset of realm-level roles
print(claims.client_roles)      # frozenset of roles for AMT_CLIENT_ID
print(claims.active_organization) # OrgMembership | None
```

## Configuration

Set these environment variables before starting your application:

| Variable | Description |
|---|---|
| `AMT_KEYCLOAK_URL` | Keycloak base URL, e.g. `https://auth.amilliontechies.com` |
| `AMT_REALM` | Realm name, e.g. `amilliontechies` |
| `AMT_CLIENT_ID` | OAuth2 client ID for your service |
| `AMT_CLIENT_SECRET` | Client secret for the Admin API client-credentials grant |

`load_config()` raises `ConfigError` immediately at startup if any value is missing or if `AMT_KEYCLOAK_URL` has no scheme.

## Token claims

After validation, `TokenClaims` gives you:

```python
@dataclass(frozen=True)
class TokenClaims:
    sub: str
    email: str | None
    name: str | None
    given_name: str | None
    family_name: str | None
    realm_roles: frozenset[str]
    client_roles: frozenset[str]          # roles scoped to AMT_CLIENT_ID
    memberships: tuple[OrgMembership, ...]
    active_organization: OrgMembership | None  # first in insertion order
    raw: dict                             # original decoded payload
```

```python
@dataclass(frozen=True)
class OrgMembership:
    id: str
    name: str
    roles: list[str]
    groups: list[GroupRef]

@dataclass(frozen=True)
class GroupRef:
    id: str
    name: str
    organization_id: str
```

Organization data comes from the `organization` JWT claim that Keycloak injects when the Organizations feature is enabled.

## Admin API

`AdminClient` wraps the Keycloak Admin REST API with automatic client-credentials token caching and a single 401-retry:

```python
from amt_auth.core.admin import AdminClient

admin = AdminClient(config)

org = admin.get_organization("b3f1a2c4-...")
members = admin.list_org_members("b3f1a2c4-...")
groups = admin.list_org_groups("b3f1a2c4-...")
user = admin.get_user("user-sub-123")
```

Non-2xx responses raise `AdminAPIError(status_code, body)`.

## Event sync

`consume_event` processes webhook events from Keycloak and writes through to a `MirrorRepository` — an interface your Django models implement:

```python
from amt_auth import MirrorRepository, consume_event

class MyDjangoRepo:
    def upsert_organization(self, id, name, synced_at): ...
    def soft_delete_organization(self, id, synced_at): ...
    def upsert_group(self, id, name, organization_id, parent_id, synced_at): ...
    def soft_delete_group(self, id, synced_at): ...
    def upsert_membership(self, user_sub, organization_id, group_id, roles, synced_at): ...
    def soft_delete_membership(self, user_sub, organization_id, group_id, synced_at): ...
    def soft_delete_memberships_by_sub(self, user_sub, synced_at): ...

consume_event(event_dict, MyDjangoRepo())
```

Supported event types: `ORG_CREATED`, `ORG_UPDATED`, `ORG_DELETED`, `ORG_GROUP_CREATED`, `ORG_GROUP_UPDATED`, `ORG_GROUP_DELETED`, `ORG_MEMBERSHIP_ADDED`, `ORG_MEMBERSHIP_REMOVED`, `USER_DELETED`.

Unknown event types are logged and silently skipped. Malformed payloads raise `SyncError`.

## Django integration

Install `amt-auth[django]`, then in `settings.py`:

```python
INSTALLED_APPS = [..., "rest_framework", "amt_auth.django"]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "amt_auth.django.authentication.KeycloakAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}

AMT_WEBHOOK_SECRET = os.environ["AMT_WEBHOOK_SECRET"]
```

Run `python manage.py migrate` to create the mirror tables (`Organization`, `Group`, `Membership`).

In a view, `request.user` is a `KeycloakUser` (never stored in the database) and `request.auth` is the `TokenClaims`:

```python
from amt_auth.django.permissions import IsOrgMember, has_client_role, has_realm_role

class ReportView(APIView):
    permission_classes = [IsOrgMember, has_realm_role("admin")]

    def get(self, request):
        org = request.auth.active_organization
        ...
```

To receive Keycloak org events, mount the webhook:

```python
urlpatterns = [path("auth/", include("amt_auth.django.urls"))]
```

`POST /auth/webhook/` requires the `X-AMT-Webhook-Secret` header to match `AMT_WEBHOOK_SECRET` and writes the event to the mirror tables through `DjangoMirrorRepository`.

### Group kinds

Clubs and mentorships are both groups inside an organization. Each organization has top-level groups (`clubs`, `mentorships`) and the real ones sit underneath, so a group's kind is its parent's name:

```python
Group.objects.get(id="...").kind   # "clubs", "mentorships", or None for a top-level group
```

### Onboarding

Admins set up organizations and bring users in through two endpoints. Both call Keycloak; the mirror tables catch up through the webhook.

| Endpoint | Who | Body |
|---|---|---|
| `POST /auth/organizations/` | realm role `admin` | `{"name": "...", "domains": ["..."]}` (domains optional) |
| `POST /auth/organizations/<id>/invitations/` | that organization's `admin`, or realm `admin` | `{"email": "...", "first_name": "...", "last_name": "..."}` (names optional) |

An invitation makes Keycloak email the user a link to register and join the organization.

## Exceptions

```
AMTAuthError              base class
  ConfigError             missing / malformed env var
  TokenExpiredError       exp in the past
  InvalidTokenError       bad signature, wrong iss/aud, unsupported alg, missing sub
  AdminAPIError           non-2xx from Keycloak Admin API
  SyncError               malformed webhook payload
```

## Development

```bash
pip install -e ".[dev]"

make test           # full run with coverage
make test-fast      # quick run, no coverage
make test-k K=expired   # run tests matching keyword
make test-file FILE=tests/test_validator.py
make cov-html       # HTML coverage report
```

### Local CI

```bash
# Install act (runs GitHub Actions locally via Docker)
curl https://raw.githubusercontent.com/nektos/act/master/install.sh | bash -s -- -b ~/.local/bin

# Run the full CI matrix
act push

# Run just Python 3.12
act push --matrix python-version:3.12 --pull=false
```

## CI

GitHub Actions runs tests against **Python 3.11 and 3.12** on every push and pull request to `main`, `develop` and `release/*`.

Two rules are enforced on pull requests:

- **Branch policy**: `main` only accepts `release/*`; `develop` only accepts `feature/*` (and `release/*` merged back).
- **Cleanup**: a `feature/*` branch is deleted automatically once its pull request is merged.

## Branch strategy

| Branch | Purpose |
|---|---|
| `feature/*` | Short-lived work; PR into `develop`, deleted on merge |
| `develop` | Integration — only merged into via PR |
| `release/x.y.z` | Cut from `develop`; bump the version here, then PR into `main` |
| `main` | Production — only merged from `release/*` via PR |

### Releasing

```bash
git checkout develop && git pull
git checkout -b release/0.2.0
# bump `version` in pyproject.toml, commit
git push -u origin release/0.2.0
# open a PR release/0.2.0 -> main, merge, then tag main as v0.2.0
# open a PR release/0.2.0 -> develop to bring the version bump back
```
