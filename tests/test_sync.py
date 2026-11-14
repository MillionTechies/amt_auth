from unittest.mock import MagicMock, call

import pytest

from amt_auth.core.admin import AdminClient
from amt_auth.core.sync import MirrorRepository, consume_event, sync_all, sync_organization
from amt_auth.exceptions import SyncError

ORG = {"id": "org-1", "name": "JKUAT", "alias": "jkuat"}
CLUBS = {"id": "g-clubs", "name": "clubs", "path": "/clubs"}
ROBOTICS = {"id": "g-robo", "name": "Robotics Club", "path": "/clubs/Robotics Club"}


@pytest.fixture()
def repo():
    return MagicMock(spec=MirrorRepository)


@pytest.fixture()
def admin():
    """An AdminClient serving one organization: clubs > Robotics Club, member alice."""
    admin = MagicMock(spec=AdminClient)
    admin.list_organizations.return_value = [ORG]
    admin.get_organization.return_value = ORG
    admin.list_org_members.return_value = [{"id": "alice"}, {"id": "bob"}]
    admin.list_org_groups.return_value = [CLUBS]
    admin.list_org_group_children.side_effect = lambda org, group: (
        [ROBOTICS] if group == "g-clubs" else []
    )
    admin.list_org_group_members.side_effect = lambda org, group: (
        [{"id": "alice"}] if group == "g-robo" else []
    )
    return admin


def _event(operation: str, resource_type: str, path: str) -> dict:
    """Keycloak's own admin event shape."""
    return {
        "realmId": "amilliontechies",
        "time": 1700000000000,
        "operationType": operation,
        "resourceType": resource_type,
        "resourcePath": path,
    }


# --- sync_organization --------------------------------------------------------


def test_sync_organization_upserts_everything(admin, repo):
    sync_organization("org-1", admin, repo)

    kw = repo.upsert_organization.call_args.kwargs
    assert (kw["id"], kw["name"], kw["alias"]) == ("org-1", "JKUAT", "jkuat")

    groups = {c.kwargs["id"]: c.kwargs["path"] for c in repo.upsert_group.call_args_list}
    assert groups == {"g-clubs": "/clubs", "g-robo": "/clubs/Robotics Club"}

    memberships = {
        (c.kwargs["user_sub"], c.kwargs["group_id"])
        for c in repo.upsert_membership.call_args_list
    }
    assert memberships == {("alice", None), ("bob", None), ("alice", "g-robo")}


def test_sync_organization_uses_one_timestamp_and_sweeps_last(admin, repo):
    sync_organization("org-1", admin, repo)

    synced_at = repo.upsert_organization.call_args.kwargs["synced_at"]
    stamps = {c.kwargs["synced_at"] for c in repo.upsert_group.call_args_list}
    stamps |= {c.kwargs["synced_at"] for c in repo.upsert_membership.call_args_list}
    assert stamps == {synced_at}
    assert repo.method_calls[-1] == call.soft_delete_stale("org-1", synced_at)


def test_sync_all_syncs_each_org_then_sweeps_organizations(admin, repo):
    admin.list_organizations.return_value = [ORG, {**ORG, "id": "org-2"}]
    assert sync_all(admin, repo) == 2
    assert repo.upsert_organization.call_count == 2
    assert repo.method_calls[-1][0] == "soft_delete_stale_organizations"


# --- consume_event --------------------------------------------------------------


@pytest.mark.parametrize(
    "operation, resource_type, path",
    [
        ("CREATE", "ORGANIZATION", "organizations/org-1"),
        ("UPDATE", "ORGANIZATION", "organizations/org-1"),
        ("CREATE", "ORGANIZATION_GROUP", "organizations/org-1/groups/g-clubs/children"),
        ("DELETE", "ORGANIZATION_GROUP", "organizations/org-1/groups/g-robo"),
        ("CREATE", "ORGANIZATION_MEMBERSHIP", "organizations/org-1/members"),
        ("DELETE", "ORGANIZATION_MEMBERSHIP", "organizations/org-1/members/alice"),
        ("CREATE", "ORGANIZATION_GROUP_MEMBERSHIP", "organizations/org-1/groups/g-robo/members/alice"),
    ],
)
def test_organization_events_resync_that_organization(admin, repo, operation, resource_type, path):
    consume_event(_event(operation, resource_type, path), admin, repo)
    admin.get_organization.assert_called_once_with("org-1")
    repo.soft_delete_stale.assert_called_once()


def test_organization_deleted_is_soft_deleted_without_resync(admin, repo):
    consume_event(_event("DELETE", "ORGANIZATION", "organizations/org-1"), admin, repo)
    assert repo.soft_delete_organization.call_args.kwargs["id"] == "org-1"
    admin.get_organization.assert_not_called()


def test_user_deleted_removes_their_memberships(admin, repo):
    consume_event(_event("DELETE", "USER", "users/alice"), admin, repo)
    assert repo.soft_delete_memberships_by_sub.call_args.kwargs["user_sub"] == "alice"


@pytest.mark.parametrize(
    "event",
    [
        _event("CREATE", "CLIENT", "clients/abc"),
        _event("UPDATE", "USER", "users/alice"),
        {"type": "LOGIN"},
        {},
    ],
)
def test_unrelated_events_are_ignored(admin, repo, event):
    consume_event(event, admin, repo)
    assert repo.method_calls == []
    assert admin.method_calls == []


@pytest.mark.parametrize(
    "event",
    [
        _event("CREATE", "ORGANIZATION", "something/else"),
        _event("CREATE", "ORGANIZATION_GROUP", ""),
        _event("DELETE", "USER", "users"),
    ],
)
def test_malformed_events_raise(admin, repo, event):
    with pytest.raises(SyncError):
        consume_event(event, admin, repo)
