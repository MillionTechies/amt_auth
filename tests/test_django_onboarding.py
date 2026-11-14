from unittest.mock import MagicMock

import pytest
from rest_framework.test import APIClient

from amt_auth.core.admin import AdminClient
from amt_auth.core.config import load_config
from amt_auth.core.service import AuthService
from amt_auth.core.validator import TokenValidator
from amt_auth.django import authentication
from amt_auth.exceptions import AdminAPIError

ORG = "org-jkuat-id"  # the organization in the default test token
PLATFORM_ADMIN = {"realm_access": {"roles": ["admin"]}}
ORG_ADMIN = {"organization": {"jkuat": {"id": ORG, "groups": ["/admins"]}}}


@pytest.fixture()
def admin(amt_env, fake_jwks_client, monkeypatch):
    cfg = load_config(amt_env)
    admin = MagicMock(spec=AdminClient)
    admin.create_organization.return_value = "org-new"
    service = AuthService(
        cfg, validator=TokenValidator(cfg, jwks_client=fake_jwks_client), admin=admin
    )
    monkeypatch.setattr(authentication, "get_auth_service", lambda: service)
    return admin


def _post(path, body, token):
    return APIClient().post(
        path, body, format="json", headers={"Authorization": f"Bearer {token}"}
    )


def test_platform_admin_creates_organization(admin, make_jwt):
    response = _post(
        "/auth/organizations/",
        {"name": "University of Nairobi", "domains": ["uonbi.ac.ke"]},
        make_jwt(PLATFORM_ADMIN),
    )
    assert response.status_code == 201
    assert response.json() == {
        "id": "org-new",
        "name": "University of Nairobi",
        "alias": "university-of-nairobi",
    }
    admin.create_organization.assert_called_once_with(
        name="University of Nairobi", alias="university-of-nairobi", domains=["uonbi.ac.ke"]
    )


def test_create_organization_accepts_explicit_alias(admin, make_jwt):
    response = _post(
        "/auth/organizations/", {"name": "UoN", "alias": "uon"}, make_jwt(PLATFORM_ADMIN)
    )
    assert response.status_code == 201
    assert admin.create_organization.call_args.kwargs["alias"] == "uon"


def test_ordinary_user_cannot_create_organization(admin, make_jwt):
    response = _post("/auth/organizations/", {"name": "UoN"}, make_jwt())
    assert response.status_code == 403
    admin.create_organization.assert_not_called()


def test_create_organization_requires_name(admin, make_jwt):
    response = _post("/auth/organizations/", {}, make_jwt(PLATFORM_ADMIN))
    assert response.status_code == 400


def test_duplicate_organization_is_409(admin, make_jwt):
    admin.create_organization.side_effect = AdminAPIError(409, "exists")
    response = _post("/auth/organizations/", {"name": "UoN"}, make_jwt(PLATFORM_ADMIN))
    assert response.status_code == 409


def test_keycloak_failure_is_502(admin, make_jwt):
    admin.create_organization.side_effect = AdminAPIError(500, "boom")
    response = _post("/auth/organizations/", {"name": "UoN"}, make_jwt(PLATFORM_ADMIN))
    assert response.status_code == 502


def test_org_admin_invites_user(admin, make_jwt):
    response = _post(
        f"/auth/organizations/{ORG}/invitations/",
        {"email": "bob@example.com", "first_name": "Bob"},
        make_jwt(ORG_ADMIN),
    )
    assert response.status_code == 204
    admin.invite_org_member.assert_called_once_with(
        ORG, email="bob@example.com", first_name="Bob", last_name=""
    )


def test_platform_admin_can_invite_to_any_org(admin, make_jwt):
    response = _post(
        "/auth/organizations/other-org/invitations/",
        {"email": "bob@example.com"},
        make_jwt(PLATFORM_ADMIN),
    )
    assert response.status_code == 204


def test_plain_member_cannot_invite(admin, make_jwt):
    response = _post(
        f"/auth/organizations/{ORG}/invitations/", {"email": "bob@example.com"}, make_jwt()
    )
    assert response.status_code == 403


def test_admin_of_another_org_cannot_invite(admin, make_jwt):
    response = _post(
        "/auth/organizations/other-org/invitations/",
        {"email": "bob@example.com"},
        make_jwt(ORG_ADMIN),
    )
    assert response.status_code == 403
    admin.invite_org_member.assert_not_called()


def test_invite_requires_valid_email(admin, make_jwt):
    response = _post(
        f"/auth/organizations/{ORG}/invitations/", {"email": "nope"}, make_jwt(ORG_ADMIN)
    )
    assert response.status_code == 400
