from __future__ import annotations

from functools import lru_cache

from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from amt_auth.core.claims import TokenClaims
from amt_auth.core.config import get_config
from amt_auth.core.service import AuthService
from amt_auth.exceptions import InvalidTokenError, TokenExpiredError


@lru_cache(maxsize=1)
def get_auth_service() -> AuthService:
    """One AuthService per process, so the JWKS key cache is shared."""
    return AuthService(get_config())


class KeycloakUser:
    """The request user, built from token claims only. Never stored in the database."""

    is_authenticated = True
    is_anonymous = False
    is_active = True

    def __init__(self, claims: TokenClaims) -> None:
        self.claims = claims
        self.id = self.pk = claims.sub
        self.email = claims.email
        self.username = claims.email or claims.sub

    def __str__(self) -> str:
        return self.username


class KeycloakAuthentication(BaseAuthentication):
    """Authenticates `Authorization: Bearer <Keycloak access token>`.

    Sets `request.user` to a `KeycloakUser` and `request.auth` to the `TokenClaims`.
    """

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != b"bearer":
            return None
        if len(parts) != 2:
            raise AuthenticationFailed("Invalid Authorization header.")
        try:
            claims = get_auth_service().validate_token(parts[1].decode())
        except (TokenExpiredError, InvalidTokenError, UnicodeError) as exc:
            raise AuthenticationFailed(str(exc)) from exc
        return KeycloakUser(claims), claims

    def authenticate_header(self, request) -> str:
        return "Bearer"
