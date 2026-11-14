from __future__ import annotations

from dataclasses import dataclass

ADMINS_GROUP = "/admins"  # members of this group administer the organization


@dataclass(frozen=True)
class GroupRef:
    """A group inside an organization, as the token names it: by path."""

    path: str  # e.g. "/clubs/Robotics Club"
    organization_id: str

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    @property
    def kind(self) -> str | None:
        """The top-level group it sits under, e.g. "clubs"; None if top-level itself."""
        parts = self.path.strip("/").split("/")
        return parts[0] if len(parts) > 1 else None


@dataclass(frozen=True)
class OrgMembership:
    id: str
    alias: str
    groups: tuple[GroupRef, ...]

    @property
    def is_admin(self) -> bool:
        return any(g.path == ADMINS_GROUP for g in self.groups)


@dataclass(frozen=True)
class TokenClaims:
    sub: str
    email: str | None
    name: str | None
    given_name: str | None
    family_name: str | None
    realm_roles: frozenset[str]
    client_roles: frozenset[str]
    memberships: tuple[OrgMembership, ...]
    active_organization: OrgMembership | None
    raw: dict

    @classmethod
    def from_decoded(cls, payload: dict, client_id: str) -> TokenClaims:
        from amt_auth.exceptions import InvalidTokenError

        sub = payload.get("sub")
        if not sub:
            raise InvalidTokenError("Token is missing 'sub' claim")

        realm_roles = frozenset(
            payload.get("realm_access", {}).get("roles", [])
        )
        client_roles = frozenset(
            payload.get("resource_access", {}).get(client_id, {}).get("roles", [])
        )

        # Keycloak's organization claim, with "Add organization id" enabled and the
        # organization group mapper added:
        #   {"<alias>": {"id": "<org id>", "groups": ["/clubs/Robotics Club"]}}
        org_claim = payload.get("organization") or {}
        if not isinstance(org_claim, dict) or not all(
            isinstance(attrs, dict) and attrs.get("id") for attrs in org_claim.values()
        ):
            raise InvalidTokenError(
                "Token 'organization' claim carries no organization IDs. Enable "
                "'Add organization id' on the realm's organization mapper."
            )
        memberships = tuple(
            OrgMembership(
                id=attrs["id"],
                alias=alias,
                groups=tuple(
                    GroupRef(path=path, organization_id=attrs["id"])
                    for path in attrs.get("groups", [])
                ),
            )
            for alias, attrs in org_claim.items()
        )

        return cls(
            sub=sub,
            email=payload.get("email"),
            name=payload.get("name"),
            given_name=payload.get("given_name"),
            family_name=payload.get("family_name"),
            realm_roles=realm_roles,
            client_roles=client_roles,
            memberships=memberships,
            active_organization=memberships[0] if memberships else None,
            raw=payload,
        )
