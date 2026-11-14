from __future__ import annotations

from amt_auth.core.admin import AdminClient
from amt_auth.core.claims import TokenClaims, OrgMembership
from amt_auth.core.config import AMTConfig
from amt_auth.core.validator import TokenValidator


class AuthService:
    """High-level facade over token validation and admin operations.

    Inject `validator` and `admin` for testing; they default to their
    concrete implementations wired to the provided config.
    """

    def __init__(
        self,
        config: AMTConfig,
        validator: TokenValidator | None = None,
        admin: AdminClient | None = None,
    ) -> None:
        self._config = config
        self._validator = validator or TokenValidator(config)
        self.admin = admin or AdminClient(config)

    def validate_token(self, raw_jwt: str) -> TokenClaims:
        """Validate a raw JWT string and return parsed claims."""
        return self._validator.validate(raw_jwt)

    def get_active_organization(
        self, claims: TokenClaims
    ) -> OrgMembership | None:
        """Return the active organization for a token.

        Phase A: returns the first membership in insertion order.
        Phase E: will honour the keycloak-orgs active-organization attribute.
        """
        return claims.active_organization
