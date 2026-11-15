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
    id: str                       # Keycloak organization ID
    alias: str                    # URL-safe key, e.g. "jkuat"
    groups: tuple[GroupRef, ...]
    is_admin: bool                # property: member of the "/admins" group

@dataclass(frozen=True)
class GroupRef:
    path: str                     # "/clubs/Robotics Club"
    organization_id: str
    name: str                     # property: "Robotics Club"
    kind: str | None              # property: "clubs"; None for a top-level group
```

Clubs and mentorships are both groups inside an organization. Each organization has top-level groups (`clubs`, `mentorships`, `admins`) and the real clubs and mentorships sit underneath, so a group's kind is the top-level group it belongs to. Keycloak has no per-organization roles; an organization's admins are the members of its `/admins` group.

### What the realm must provide

The library reads Keycloak's `organization` claim in this shape:

```json
{"organization": {"jkuat": {"id": "f355e756-...", "groups": ["/clubs/Robotics Club", "/admins"]}}}
```

Keycloak does not produce that by default. On the realm's `organization` client scope:

- turn on **Add organization id** on the organization membership mapper (the default claim is a bare list of aliases, which the library rejects with `InvalidTokenError`)
- add an **Organization Group Membership** mapper

Clients must request the `organization` scope, and the token's `aud` must include `AMT_CLIENT_ID` (an audience mapper on the frontend's client). `scripts/keycloak-dev-setup.sh` does all of this for a local realm.

## Admin API

`AdminClient` wraps the Keycloak Admin REST API with automatic client-credentials token caching and a single 401-retry. List methods follow pagination and return every item.

```python
from amt_auth.core.admin import AdminClient

admin = AdminClient(config)

admin.list_organizations()
admin.get_organization(org_id)
admin.list_org_members(org_id)
admin.list_org_groups(org_id)                    # top-level groups
admin.list_org_group_children(org_id, group_id)
admin.list_org_group_members(org_id, group_id)
admin.get_user(user_id)

admin.create_organization("University of Nairobi", alias="uon")   # returns the new ID
admin.add_org_member(org_id, user_id)
admin.invite_org_member(org_id, "bob@example.com")   # needs SMTP configured on the realm
```

Non-2xx responses raise `AdminAPIError(status_code, body)`.

The client's service account needs the `kc-admin-api` client scope (without it Keycloak answers 401) and these `realm-management` roles: `manage-organizations`, `view-organizations`, `manage-users`, `view-users`, `query-users`, `query-groups`.

## Mirror sync

Products that need to query organizations, groups and memberships keep a local mirror. The library fills it from the Admin API through a `MirrorRepository`, an interface your storage implements (the Django integration ships one):

```python
from amt_auth.core.sync import consume_event, sync_all, sync_organization

sync_all(admin, repo)                    # make the whole mirror match Keycloak
sync_organization(org_id, admin, repo)   # one organization
consume_event(event, admin, repo)        # react to one Keycloak admin event
```

A sync upserts everything Keycloak has, then soft-deletes whatever it no longer has.

`consume_event` takes Keycloak's own admin event (`operationType`, `resourceType`, `resourcePath`). Keycloak's events do not carry enough to update the mirror directly (a membership event does not name the user), so any event about an organization re-syncs that organization. A deleted organization or user is soft-deleted, unrelated events are ignored, and malformed ones raise `SyncError`.

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

`POST /auth/webhook/` requires the `X-AMT-Webhook-Secret` header to match `AMT_WEBHOOK_SECRET` and re-syncs the organization the event touches. Keycloak has no built-in webhooks, so delivering events needs an event-listener extension; without one, run the full sync on a schedule:

```bash
python manage.py amt_sync
```

### Group kinds

```python
Group.objects.get(id="...").kind   # "clubs", "mentorships", or None for a top-level group
```

### Onboarding

Admins set up organizations and bring users in through two endpoints. Both call Keycloak; the mirror tables catch up through the webhook.

| Endpoint | Who | Body |
|---|---|---|
| `POST /auth/organizations/` | realm role `admin` | `{"name": "...", "alias": "...", "domains": ["..."]}` (alias defaults to a slug of the name; domains optional) |
| `POST /auth/organizations/<id>/invitations/` | a member of that organization's `/admins` group, or realm `admin` | `{"email": "...", "first_name": "...", "last_name": "..."}` (names optional) |

An invitation makes Keycloak email the user a link to register and join the organization, so the realm needs SMTP configured.

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

## Frontend

`frontend/` is the Vite + React app that signs in with Keycloak, and `backend/` is the small Django project it talks to, which mounts `amt_auth.django`. See [frontend/README.md](frontend/README.md).

## CI

GitHub Actions runs tests against **Python 3.11 and 3.12** on every push and pull request to `main`, `develop` and `release/*`. The frontend is linted and built in the same run.

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

Pushing the tag publishes that version to [PyPI](https://pypi.org/project/amt-auth/) through `.github/workflows/publish.yml`. The tag must match the version in `pyproject.toml`, and a version can only be published once.

## License

MIT. See [LICENSE](LICENSE).
