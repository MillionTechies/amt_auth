from unittest.mock import MagicMock

import pytest

from amt_auth.core.sync import MirrorRepository, consume_event
from amt_auth.exceptions import SyncError


def _repo() -> MagicMock:
    return MagicMock(spec=MirrorRepository)


def _event(type_: str, representation: dict) -> dict:
    return {
        "type": type_,
        "realmId": "amilliontechies",
        "time": 1700000000000,
        "representation": representation,
    }


# ---------------------------------------------------------------------------
# Organization events
# ---------------------------------------------------------------------------

def test_org_created():
    repo = _repo()
    consume_event(_event("ORG_CREATED", {"id": "org-1", "name": "JKUAT"}), repo)
    repo.upsert_organization.assert_called_once()
    kw = repo.upsert_organization.call_args.kwargs
    assert kw["id"] == "org-1"
    assert kw["name"] == "JKUAT"


def test_org_updated():
    repo = _repo()
    consume_event(_event("ORG_UPDATED", {"id": "org-1", "name": "JKUAT Updated"}), repo)
    repo.upsert_organization.assert_called_once()
    kw = repo.upsert_organization.call_args.kwargs
    assert kw["name"] == "JKUAT Updated"


def test_org_deleted():
    repo = _repo()
    consume_event(_event("ORG_DELETED", {"id": "org-1"}), repo)
    repo.soft_delete_organization.assert_called_once()
    kw = repo.soft_delete_organization.call_args.kwargs
    assert kw["id"] == "org-1"


# ---------------------------------------------------------------------------
# Org group events
# ---------------------------------------------------------------------------

def test_group_created():
    repo = _repo()
    consume_event(
        _event("ORG_GROUP_CREATED", {"id": "g-1", "name": "Robotics", "organizationId": "org-1"}),
        repo,
    )
    repo.upsert_group.assert_called_once()
    kw = repo.upsert_group.call_args.kwargs
    assert kw["id"] == "g-1"
    assert kw["organization_id"] == "org-1"
    assert kw["parent_id"] is None


def test_group_created_with_parent():
    repo = _repo()
    consume_event(
        _event(
            "ORG_GROUP_CREATED",
            {"id": "g-1", "name": "Robotics", "organizationId": "org-1", "parentId": "g-clubs"},
        ),
        repo,
    )
    assert repo.upsert_group.call_args.kwargs["parent_id"] == "g-clubs"


def test_group_updated():
    repo = _repo()
    consume_event(
        _event("ORG_GROUP_UPDATED", {"id": "g-1", "name": "Robotics v2", "organizationId": "org-1"}),
        repo,
    )
    repo.upsert_group.assert_called_once()


def test_group_deleted():
    repo = _repo()
    consume_event(_event("ORG_GROUP_DELETED", {"id": "g-1"}), repo)
    repo.soft_delete_group.assert_called_once()
    kw = repo.soft_delete_group.call_args.kwargs
    assert kw["id"] == "g-1"


# ---------------------------------------------------------------------------
# Membership events
# ---------------------------------------------------------------------------

def test_membership_added():
    repo = _repo()
    consume_event(
        _event("ORG_MEMBERSHIP_ADDED", {
            "userId": "sub-alice",
            "organizationId": "org-1",
            "roles": ["member"],
        }),
        repo,
    )
    repo.upsert_membership.assert_called_once()
    kw = repo.upsert_membership.call_args.kwargs
    assert kw["user_sub"] == "sub-alice"
    assert kw["organization_id"] == "org-1"
    assert kw["roles"] == ["member"]


def test_membership_removed():
    repo = _repo()
    consume_event(
        _event("ORG_MEMBERSHIP_REMOVED", {"userId": "sub-alice", "organizationId": "org-1"}),
        repo,
    )
    repo.soft_delete_membership.assert_called_once()
    kw = repo.soft_delete_membership.call_args.kwargs
    assert kw["user_sub"] == "sub-alice"


def test_user_deleted():
    repo = _repo()
    consume_event(_event("USER_DELETED", {"userId": "sub-alice"}), repo)
    repo.soft_delete_memberships_by_sub.assert_called_once()
    kw = repo.soft_delete_memberships_by_sub.call_args.kwargs
    assert kw["user_sub"] == "sub-alice"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_unknown_event_type_skipped():
    repo = _repo()
    consume_event(_event("SOME_FUTURE_EVENT", {"id": "x"}), repo)
    repo.upsert_organization.assert_not_called()
    repo.soft_delete_organization.assert_not_called()
    repo.upsert_group.assert_not_called()
    repo.upsert_membership.assert_not_called()


def test_idempotent_double_upsert():
    repo = _repo()
    evt = _event("ORG_CREATED", {"id": "org-1", "name": "JKUAT"})
    consume_event(evt, repo)
    consume_event(evt, repo)
    assert repo.upsert_organization.call_count == 2


def test_malformed_payload_raises():
    repo = _repo()
    evt = _event("ORG_CREATED", {})  # missing "id" and "name"
    with pytest.raises(SyncError):
        consume_event(evt, repo)


def test_membership_added_optional_group_id():
    """group_id (groupId) is optional for direct org membership."""
    repo = _repo()
    consume_event(
        _event("ORG_MEMBERSHIP_ADDED", {
            "userId": "sub-bob",
            "organizationId": "org-1",
        }),
        repo,
    )
    kw = repo.upsert_membership.call_args.kwargs
    assert kw["group_id"] is None
