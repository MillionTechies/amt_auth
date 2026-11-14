from unittest.mock import MagicMock

import pytest

from amt_auth.core.claims import TokenClaims, OrgMembership
from amt_auth.core.config import load_config
from amt_auth.core.service import AuthService
from amt_auth.core.validator import TokenValidator
from amt_auth.exceptions import TokenExpiredError


def _make_service(amt_env: dict, fake_jwks_client) -> AuthService:
    cfg = load_config(amt_env)
    validator = TokenValidator(cfg, jwks_client=fake_jwks_client)
    return AuthService(cfg, validator=validator, admin=MagicMock())


def test_validate_token_returns_claims(amt_env, make_jwt, fake_jwks_client):
    svc = _make_service(amt_env, fake_jwks_client)
    claims = svc.validate_token(make_jwt())
    assert claims.sub == "user-sub-123"


def test_validate_token_propagates_expired(amt_env):
    cfg = load_config(amt_env)
    mock_validator = MagicMock(spec=TokenValidator)
    mock_validator.validate.side_effect = TokenExpiredError("expired")
    svc = AuthService(cfg, validator=mock_validator, admin=MagicMock())
    with pytest.raises(TokenExpiredError):
        svc.validate_token("any.jwt.token")


def test_get_active_organization_with_membership(amt_env):
    cfg = load_config(amt_env)
    mem = OrgMembership(id="u1", name="JKUAT", roles=("member",), groups=())
    claims = MagicMock(spec=TokenClaims)
    claims.active_organization = mem
    svc = AuthService(cfg, validator=MagicMock(), admin=MagicMock())
    assert svc.get_active_organization(claims) is mem


def test_get_active_organization_none(amt_env):
    cfg = load_config(amt_env)
    claims = MagicMock(spec=TokenClaims)
    claims.active_organization = None
    svc = AuthService(cfg, validator=MagicMock(), admin=MagicMock())
    assert svc.get_active_organization(claims) is None
