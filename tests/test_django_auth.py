import time
from unittest.mock import MagicMock

import pytest
from rest_framework.test import APIClient

from amt_auth.core.config import load_config
from amt_auth.core.service import AuthService
from amt_auth.core.validator import TokenValidator
from amt_auth.django import authentication


@pytest.fixture()
def client(amt_env, fake_jwks_client, monkeypatch):
    cfg = load_config(amt_env)
    service = AuthService(
        cfg, validator=TokenValidator(cfg, jwks_client=fake_jwks_client), admin=MagicMock()
    )
    monkeypatch.setattr(authentication, "get_auth_service", lambda: service)
    return APIClient()


def _get(client, path, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.get(path, headers=headers)


def test_valid_token_sets_user_and_claims(client, make_jwt):
    response = _get(client, "/me/", make_jwt())
    assert response.status_code == 200
    assert response.json() == {"sub": "user-sub-123", "email": "alice@gmail.com"}


def test_missing_token_is_401(client):
    response = _get(client, "/me/")
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == "Bearer"


def test_expired_token_is_401(client, make_jwt):
    response = _get(client, "/me/", make_jwt({"exp": int(time.time()) - 10}))
    assert response.status_code == 401


def test_garbage_token_is_401(client):
    assert _get(client, "/me/", "not-a-jwt").status_code == 401


def test_malformed_header_is_401(client):
    response = client.get("/me/", headers={"Authorization": "Bearer a b"})
    assert response.status_code == 401


def test_org_member_allowed(client, make_jwt):
    assert _get(client, "/org-only/", make_jwt()).status_code == 200


def test_user_without_org_forbidden(client, make_jwt):
    assert _get(client, "/org-only/", make_jwt({"organization": {}})).status_code == 403


def test_realm_role_missing_forbidden(client, make_jwt):
    assert _get(client, "/realm-admin/", make_jwt()).status_code == 403


def test_realm_role_present_allowed(client, make_jwt):
    token = make_jwt({"realm_access": {"roles": ["admin"]}})
    assert _get(client, "/realm-admin/", token).status_code == 200


def test_client_role_present_allowed(client, make_jwt):
    assert _get(client, "/client-read/", make_jwt()).status_code == 200


def test_client_role_missing_forbidden(client, make_jwt):
    token = make_jwt({"resource_access": {}})
    assert _get(client, "/client-read/", token).status_code == 403
