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
        "jkuat": {"id": "org-a", "groups": ["/clubs/Robotics Club", "/mentorships/Web Dev"]},
        "uonbi": {"id": "org-b", "groups": ["/admins"]},
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
        "organization": {"jkuat": {"id": "org-a"}},
    }
    claims = TokenClaims.from_decoded(payload, "my-client")
    assert claims.active_organization is not None
    assert claims.active_organization.id == "org-a"
    assert claims.active_organization.alias == "jkuat"
    assert claims.active_organization.groups == ()


def test_two_orgs_active_is_first_in_insertion_order():
    claims = TokenClaims.from_decoded(BASE_PAYLOAD, "my-client")
    assert claims.active_organization is not None
    assert claims.active_organization.id == "org-a"


def test_groups_parsed_with_kind():
    claims = TokenClaims.from_decoded(BASE_PAYLOAD, "my-client")
    robotics, web_dev = claims.memberships[0].groups
    assert (robotics.name, robotics.kind) == ("Robotics Club", "clubs")
    assert (web_dev.name, web_dev.kind) == ("Web Dev", "mentorships")
    assert robotics.organization_id == "org-a"


def test_admins_group_makes_org_admin():
    claims = TokenClaims.from_decoded(BASE_PAYLOAD, "my-client")
    jkuat, uonbi = claims.memberships
    assert not jkuat.is_admin
    assert uonbi.is_admin
    assert uonbi.groups[0].kind is None  # top-level group


@pytest.mark.parametrize("claim", [["jkuat"], {"jkuat": {}}, {"jkuat": "x"}])
def test_organization_claim_without_ids_is_rejected(claim):
    """Keycloak's default claim is a bare list of aliases; we need the IDs."""
    with pytest.raises(InvalidTokenError, match="Add organization id"):
        TokenClaims.from_decoded({**BASE_PAYLOAD, "organization": claim}, "my-client")


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
