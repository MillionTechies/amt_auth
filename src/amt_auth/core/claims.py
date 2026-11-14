from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GroupRef:
    id: str
    name: str
    organization_id: str


@dataclass(frozen=True)
class OrgMembership:
    id: str
    name: str
    roles: tuple[str, ...]
    groups: tuple[GroupRef, ...]


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

        # organization claim: {"<org_id>": {"name": "...", "roles": [...]}}
        org_map: dict = payload.get("organization", {})
        memberships = tuple(
            OrgMembership(
                id=org_id,
                name=attrs.get("name", ""),
                roles=tuple(attrs.get("roles", [])),
                groups=(),  # org groups are not present in the base token
            )
            for org_id, attrs in org_map.items()
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
