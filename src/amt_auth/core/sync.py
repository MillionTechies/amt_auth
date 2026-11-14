from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from amt_auth.exceptions import SyncError

logger = logging.getLogger(__name__)


@runtime_checkable
class MirrorRepository(Protocol):
    def upsert_organization(self, id: str, name: str, synced_at: datetime) -> None: ...
    def soft_delete_organization(self, id: str, synced_at: datetime) -> None: ...
    def upsert_group(
        self,
        id: str,
        name: str,
        organization_id: str,
        parent_id: str | None,
        synced_at: datetime,
    ) -> None: ...
    def soft_delete_group(self, id: str, synced_at: datetime) -> None: ...
    def upsert_membership(
        self,
        user_sub: str,
        organization_id: str,
        group_id: str | None,
        roles: list[str],
        synced_at: datetime,
    ) -> None: ...
    def soft_delete_membership(
        self,
        user_sub: str,
        organization_id: str,
        group_id: str | None,
        synced_at: datetime,
    ) -> None: ...
    def soft_delete_memberships_by_sub(
        self, user_sub: str, synced_at: datetime
    ) -> None: ...


# ---------------------------------------------------------------------------
# Handlers — one per supported event type
# ---------------------------------------------------------------------------

def _require(event: dict, *keys: str) -> None:
    """Raise SyncError if any key is missing from event['representation']."""
    r = event.get("representation", {})
    missing = [k for k in keys if k not in r]
    if missing:
        raise SyncError(
            f"Event {event.get('type')!r} missing representation keys: {missing}"
        )


def _handle_org_upsert(event: dict, repo: MirrorRepository, synced_at: datetime) -> None:
    _require(event, "id", "name")
    r = event["representation"]
    repo.upsert_organization(id=r["id"], name=r["name"], synced_at=synced_at)


def _handle_org_delete(event: dict, repo: MirrorRepository, synced_at: datetime) -> None:
    _require(event, "id")
    r = event["representation"]
    repo.soft_delete_organization(id=r["id"], synced_at=synced_at)


def _handle_group_upsert(event: dict, repo: MirrorRepository, synced_at: datetime) -> None:
    _require(event, "id", "name", "organizationId")
    r = event["representation"]
    repo.upsert_group(
        id=r["id"],
        name=r["name"],
        organization_id=r["organizationId"],
        parent_id=r.get("parentId"),
        synced_at=synced_at,
    )


def _handle_group_delete(event: dict, repo: MirrorRepository, synced_at: datetime) -> None:
    _require(event, "id")
    r = event["representation"]
    repo.soft_delete_group(id=r["id"], synced_at=synced_at)


def _handle_membership_add(event: dict, repo: MirrorRepository, synced_at: datetime) -> None:
    _require(event, "userId", "organizationId")
    r = event["representation"]
    repo.upsert_membership(
        user_sub=r["userId"],
        organization_id=r["organizationId"],
        group_id=r.get("groupId"),
        roles=r.get("roles", []),
        synced_at=synced_at,
    )


def _handle_membership_remove(event: dict, repo: MirrorRepository, synced_at: datetime) -> None:
    _require(event, "userId", "organizationId")
    r = event["representation"]
    repo.soft_delete_membership(
        user_sub=r["userId"],
        organization_id=r["organizationId"],
        group_id=r.get("groupId"),
        synced_at=synced_at,
    )


def _handle_user_deleted(event: dict, repo: MirrorRepository, synced_at: datetime) -> None:
    _require(event, "userId")
    r = event["representation"]
    repo.soft_delete_memberships_by_sub(user_sub=r["userId"], synced_at=synced_at)


_REGISTRY: dict[str, object] = {
    "ORG_CREATED": _handle_org_upsert,
    "ORG_UPDATED": _handle_org_upsert,
    "ORG_DELETED": _handle_org_delete,
    "ORG_GROUP_CREATED": _handle_group_upsert,
    "ORG_GROUP_UPDATED": _handle_group_upsert,
    "ORG_GROUP_DELETED": _handle_group_delete,
    "ORG_MEMBERSHIP_ADDED": _handle_membership_add,
    "ORG_MEMBERSHIP_REMOVED": _handle_membership_remove,
    "USER_DELETED": _handle_user_deleted,
}


def consume_event(event: dict, repo: MirrorRepository) -> None:
    """Process one webhook event and write through to the mirror repository.

    - Unknown event types are logged and silently skipped.
    - Malformed payloads (missing required keys) raise SyncError.
    - Callers are responsible for transaction management.
    - This function is idempotent: all writes are upserts or soft-deletes.
    """
    event_type = event.get("type", "")
    handler = _REGISTRY.get(event_type)
    if handler is None:
        logger.warning("amt-auth sync: unknown event type %r — skipping", event_type)
        return

    synced_at = datetime.now(tz=timezone.utc)
    handler(event, repo, synced_at)  # type: ignore[call-arg]
