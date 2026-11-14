from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from amt_auth.core.admin import AdminClient
from amt_auth.exceptions import SyncError

logger = logging.getLogger(__name__)


@runtime_checkable
class MirrorRepository(Protocol):
    def upsert_organization(
        self, id: str, name: str, alias: str, synced_at: datetime
    ) -> None: ...
    def soft_delete_organization(self, id: str, synced_at: datetime) -> None: ...
    def upsert_group(
        self, id: str, name: str, path: str, organization_id: str, synced_at: datetime
    ) -> None: ...
    def upsert_membership(
        self,
        user_sub: str,
        organization_id: str,
        group_id: str | None,
        synced_at: datetime,
    ) -> None: ...
    def soft_delete_stale(self, organization_id: str, synced_at: datetime) -> None:
        """Soft-delete the organization's groups and memberships not synced at `synced_at`."""
        ...
    def soft_delete_stale_organizations(self, synced_at: datetime) -> None:
        """Soft-delete every organization not synced at `synced_at`."""
        ...
    def soft_delete_memberships_by_sub(
        self, user_sub: str, synced_at: datetime
    ) -> None: ...


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def sync_organization(
    organization_id: str,
    admin: AdminClient,
    repo: MirrorRepository,
    synced_at: datetime | None = None,
) -> None:
    """Make the mirror match Keycloak for one organization.

    Reads the organization, its groups and its members from the Admin API,
    upserts them, then soft-deletes whatever Keycloak no longer has.
    Callers are responsible for transaction management.
    """
    synced_at = synced_at or _now()
    org = admin.get_organization(organization_id)
    repo.upsert_organization(
        id=org["id"], name=org["name"], alias=org["alias"], synced_at=synced_at
    )
    for member in admin.list_org_members(organization_id):
        repo.upsert_membership(
            user_sub=member["id"],
            organization_id=organization_id,
            group_id=None,
            synced_at=synced_at,
        )

    pending = admin.list_org_groups(organization_id)
    while pending:
        group = pending.pop()
        repo.upsert_group(
            id=group["id"],
            name=group["name"],
            path=group["path"],
            organization_id=organization_id,
            synced_at=synced_at,
        )
        for member in admin.list_org_group_members(organization_id, group["id"]):
            repo.upsert_membership(
                user_sub=member["id"],
                organization_id=organization_id,
                group_id=group["id"],
                synced_at=synced_at,
            )
        pending += admin.list_org_group_children(organization_id, group["id"])

    repo.soft_delete_stale(organization_id, synced_at)


def sync_all(admin: AdminClient, repo: MirrorRepository) -> int:
    """Make the whole mirror match Keycloak. Returns the number of organizations."""
    synced_at = _now()
    organizations = admin.list_organizations()
    for org in organizations:
        sync_organization(org["id"], admin, repo, synced_at)
    repo.soft_delete_stale_organizations(synced_at)
    return len(organizations)


def consume_event(event: dict, admin: AdminClient, repo: MirrorRepository) -> None:
    """Apply one Keycloak admin event to the mirror.

    `event` is Keycloak's own admin event: `operationType`, `resourceType`
    and `resourcePath`. The events do not carry enough to update the mirror
    directly (a membership event does not name the user), so any change to an
    organization re-syncs that organization from the Admin API.

    - Events about anything else are logged and skipped.
    - Malformed events raise SyncError.
    """
    operation = event.get("operationType", "")
    resource_type = event.get("resourceType", "")
    parts = str(event.get("resourcePath", "")).split("/")
    synced_at = _now()

    if resource_type == "USER" and operation == "DELETE":
        if len(parts) < 2 or parts[0] != "users":
            raise SyncError(f"Unexpected resourcePath for USER event: {parts}")
        repo.soft_delete_memberships_by_sub(user_sub=parts[1], synced_at=synced_at)
    elif resource_type.startswith("ORGANIZATION"):
        if len(parts) < 2 or parts[0] != "organizations":
            raise SyncError(f"Unexpected resourcePath for {resource_type} event: {parts}")
        if resource_type == "ORGANIZATION" and operation == "DELETE":
            repo.soft_delete_organization(id=parts[1], synced_at=synced_at)
        else:
            sync_organization(parts[1], admin, repo, synced_at)
    else:
        logger.info("amt-auth sync: ignoring %s %s event", operation, resource_type)
