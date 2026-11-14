from __future__ import annotations

from rest_framework.permissions import BasePermission

ORG_ADMIN_ROLE = "admin"  # role inside an organization
PLATFORM_ADMIN_ROLE = "admin"  # realm role


class IsOrgMember(BasePermission):
    """Allows users whose token carries at least one organization membership."""

    def has_permission(self, request, view) -> bool:
        claims = getattr(request.user, "claims", None)
        return claims is not None and claims.active_organization is not None


class IsOrgAdmin(BasePermission):
    """Allows admins of the organization named by the URL's `organization_id`."""

    def has_permission(self, request, view) -> bool:
        claims = getattr(request.user, "claims", None)
        org_id = view.kwargs.get("organization_id")
        return claims is not None and any(
            m.id == org_id and ORG_ADMIN_ROLE in m.roles for m in claims.memberships
        )


def _has_role(claims_attr: str, role: str) -> type[BasePermission]:
    class HasRole(BasePermission):
        def has_permission(self, request, view) -> bool:
            claims = getattr(request.user, "claims", None)
            return claims is not None and role in getattr(claims, claims_attr)

    return HasRole


def has_realm_role(role: str) -> type[BasePermission]:
    """`permission_classes = [has_realm_role("admin")]`"""
    return _has_role("realm_roles", role)


def has_client_role(role: str) -> type[BasePermission]:
    """`permission_classes = [has_client_role("editor")]` (roles of AMT_CLIENT_ID)."""
    return _has_role("client_roles", role)


IsPlatformAdmin = has_realm_role(PLATFORM_ADMIN_ROLE)
