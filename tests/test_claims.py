import pytest
from amt_auth.core.claims import TokenClaims
from amt_auth.exceptions import InvalidTokenError

BASE_PAYLOAD = {
    "sub": "user-123",
    "email": "alice@gmail.com",
    "name": "Alice",
    "given_name": "Alice",
    "family_name": "Wanjiku",
    "realm_access": {"roles": ["user", "network_admin"]},
    "resource_access": {"my-client": {"roles": ["read"]}},
    "organization": {
        "org-a": {"name": "JKUAT", "roles": ["member"]},
        "org-b": {"name": "UoNBI", "roles": ["admin", "member"]},
    },
}


def test_full_payload():
    claims = TokenClaims.from_decoded(BASE_PAYLOAD, "my-client")
    assert claims.sub == "user-123"
    assert claims.email == "alice@gmail.com"
    assert claims.name == "Alice"
    assert claims.given_name == "Alice"
    assert claims.family_name == "Wanjiku"
    assert len(claims.memberships) == 2


def test_no_organization_claim():
    payload = {**BASE_PAYLOAD, "organization": {}}
    claims = TokenClaims.from_decoded(payload, "my-client")
    assert claims.memberships == ()
    assert claims.active_organization is None


def test_absent_organization_key():
    payload = {k: v for k, v in BASE_PAYLOAD.items() if k != "organization"}
    claims = TokenClaims.from_decoded(payload, "my-client")
    assert claims.memberships == ()
    assert claims.active_organization is None


def test_one_org_active_organization():
    payload = {
        **BASE_PAYLOAD,
        "organization": {"org-a": {"name": "JKUAT", "roles": ["member"]}},
    }
    claims = TokenClaims.from_decoded(payload, "my-client")
    assert claims.active_organization is not None
    assert claims.active_organization.id == "org-a"
    assert claims.active_organization.name == "JKUAT"


def test_two_orgs_active_is_first_in_insertion_order():
    claims = TokenClaims.from_decoded(BASE_PAYLOAD, "my-client")
    assert claims.active_organization is not None
    assert claims.active_organization.id == "org-a"


def test_membership_roles_parsed():
    claims = TokenClaims.from_decoded(BASE_PAYLOAD, "my-client")
    uni_b = next(m for m in claims.memberships if m.id == "org-b")
    assert "admin" in uni_b.roles
    assert "member" in uni_b.roles


def test_realm_roles():
    claims = TokenClaims.from_decoded(BASE_PAYLOAD, "my-client")
    assert claims.realm_roles == frozenset({"user", "network_admin"})


def test_client_roles():
    claims = TokenClaims.from_decoded(BASE_PAYLOAD, "my-client")
    assert "read" in claims.client_roles


def test_no_client_resource_access():
    payload = {**BASE_PAYLOAD, "resource_access": {}}
    claims = TokenClaims.from_decoded(payload, "my-client")
    assert claims.client_roles == frozenset()


def test_missing_sub_raises():
    payload = {k: v for k, v in BASE_PAYLOAD.items() if k != "sub"}
    with pytest.raises(InvalidTokenError):
        TokenClaims.from_decoded(payload, "my-client")


def test_raw_preserved():
    claims = TokenClaims.from_decoded(BASE_PAYLOAD, "my-client")
    assert claims.raw is BASE_PAYLOAD
