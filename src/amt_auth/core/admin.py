from __future__ import annotations

import time

import httpx

from amt_auth.core.config import AMTConfig
from amt_auth.exceptions import AdminAPIError

_PAGE_SIZE = 100


class AdminClient:
    """Wraps the Keycloak Admin REST API.

    Uses client-credentials to obtain an access token, caches it, and
    refreshes automatically. On a 401 from any method the token is cleared
    and one retry is attempted.

    All methods return raw dicts/lists as returned by Keycloak. Callers
    are responsible for interpreting the response shapes.
    """

    def __init__(
        self,
        config: AMTConfig,
        http: httpx.Client | None = None,
    ) -> None:
        self._config = config
        self._http = http or httpx.Client()
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _ensure_token(self) -> None:
        if self._token and time.monotonic() < self._token_expires_at:
            return
        self._fetch_token()

    def _fetch_token(self) -> None:
        cfg = self._config
        url = f"{cfg.keycloak_url}/realms/{cfg.realm}/protocol/openid-connect/token"
        response = self._http.post(
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": cfg.client_id,
                "client_secret": cfg.client_secret,
            },
        )
        if not response.is_success:
            raise AdminAPIError(response.status_code, response.text)
        data = response.json()
        self._token = data["access_token"]
        # Expire 30s before the actual expiry to avoid races
        self._token_expires_at = time.monotonic() + data.get("expires_in", 60) - 30

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        self._ensure_token()
        url = f"{self._config.keycloak_url}/admin/realms/{self._config.realm}{path}"
        response = self._http.request(method, url, headers=self._auth_headers(), **kwargs)
        if response.status_code == 401:
            # Token may have been invalidated server-side; refresh once and retry
            self._token = None
            self._fetch_token()
            response = self._http.request(
                method, url, headers=self._auth_headers(), **kwargs
            )
        if not response.is_success:
            raise AdminAPIError(response.status_code, response.text)
        return response

    def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        return self._request("GET", path, params=params)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _get_all(self, path: str) -> list[dict]:
        """Fetch every page of a list endpoint."""
        items: list[dict] = []
        while True:
            page = self._get(path, params={"first": len(items), "max": _PAGE_SIZE}).json()
            items += page
            if len(page) < _PAGE_SIZE:
                return items

    def get_organization(self, org_id: str) -> dict:
        return self._get(f"/organizations/{org_id}").json()

    def list_organizations(self) -> list[dict]:
        return self._get_all("/organizations")

    def list_org_members(self, org_id: str) -> list[dict]:
        return self._get_all(f"/organizations/{org_id}/members")

    def list_org_groups(self, org_id: str) -> list[dict]:
        """Top-level groups only; use `list_org_group_children` to walk down."""
        return self._get_all(f"/organizations/{org_id}/groups")

    def list_org_group_children(self, org_id: str, group_id: str) -> list[dict]:
        return self._get_all(f"/organizations/{org_id}/groups/{group_id}/children")

    def list_org_group_members(self, org_id: str, group_id: str) -> list[dict]:
        return self._get_all(f"/organizations/{org_id}/groups/{group_id}/members")

    def get_user(self, user_id: str) -> dict:
        return self._get(f"/users/{user_id}").json()

    # ------------------------------------------------------------------
    # Onboarding
    # ------------------------------------------------------------------

    def create_organization(
        self, name: str, alias: str, domains: list[str] | None = None
    ) -> str:
        """Create an organization and return its Keycloak ID.

        `alias` is the URL-safe key the token uses for the organization; it
        cannot contain spaces and cannot be changed later.
        """
        response = self._request(
            "POST",
            "/organizations",
            json={
                "name": name,
                "alias": alias,
                "domains": [{"name": d} for d in domains or []],
            },
        )
        return response.headers["Location"].rstrip("/").rsplit("/", 1)[-1]

    def invite_org_member(
        self,
        org_id: str,
        email: str,
        first_name: str = "",
        last_name: str = "",
    ) -> None:
        """Email an invitation; the user registers and joins the organization."""
        self._request(
            "POST",
            f"/organizations/{org_id}/members/invite-user",
            data={"email": email, "firstName": first_name, "lastName": last_name},
        )

    def add_org_member(self, org_id: str, user_id: str) -> None:
        """Add an existing Keycloak user to an organization."""
        self._request("POST", f"/organizations/{org_id}/members", json=user_id)
