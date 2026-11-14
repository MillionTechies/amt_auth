from datetime import datetime, timezone
from io import StringIO
from unittest.mock import MagicMock

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from amt_auth import MirrorRepository
from amt_auth.core.admin import AdminClient
from amt_auth.core.sync import sync_all
from amt_auth.django import authentication
from amt_auth.django.models import Group, Membership, Organization
from amt_auth.django.repository import DjangoMirrorRepository
from amt_auth.exceptions import AdminAPIError

pytestmark = pytest.mark.django_db

T1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 1, 2, tzinfo=timezone.utc)

ORG = {"id": "org-1", "name": "JKUAT", "alias": "jkuat"}
CLUBS = {"id": "g-clubs", "name": "clubs", "path": "/clubs"}
ROBOTICS = {"id": "g-robo", "name": "Robotics Club", "path": "/clubs/Robotics Club"}


@pytest.fixture()
def repo():
    repo = DjangoMirrorRepository()
    repo.upsert_organization("org-1", "JKUAT", "jkuat", T1)
    repo.upsert_group("g-clubs", "clubs", "/clubs", "org-1", T1)
    repo.upsert_group("g-robo", "Robotics Club", "/clubs/Robotics Club", "org-1", T1)
    repo.upsert_membership("alice", "org-1", None, T1)
    repo.upsert_membership("alice", "org-1", "g-robo", T1)
    return repo


@pytest.fixture()
def admin(monkeypatch):
    """A fake Keycloak holding one organization: clubs > Robotics Club, member alice."""
    admin = MagicMock(spec=AdminClient)
    admin.list_organizations.return_value = [ORG]
    admin.get_organization.return_value = ORG
    admin.list_org_members.return_value = [{"id": "alice"}]
    admin.list_org_groups.return_value = [CLUBS]
    admin.list_org_group_children.side_effect = lambda org, group: (
        [ROBOTICS] if group == "g-clubs" else []
    )
    admin.list_org_group_members.side_effect = lambda org, group: (
        [{"id": "alice"}] if group == "g-robo" else []
    )
    monkeypatch.setattr(authentication, "get_auth_service", lambda: MagicMock(admin=admin))
    return admin


def _live(model):
    return model.objects.filter(deleted_at=None)


# --- repository -------------------------------------------------------------------


def test_satisfies_protocol():
    assert isinstance(DjangoMirrorRepository(), MirrorRepository)


def test_group_kind_comes_from_path(repo):
    assert Group.objects.get(id="g-robo").kind == "clubs"
    assert Group.objects.get(id="g-clubs").kind is None


def test_upsert_is_idempotent_and_updates(repo):
    repo.upsert_organization("org-1", "JKUAT Main", "jkuat", T2)
    repo.upsert_membership("alice", "org-1", None, T2)
    assert Organization.objects.get().name == "JKUAT Main"
    assert Membership.objects.count() == 2


def test_soft_delete_org_cascades(repo):
    repo.soft_delete_organization("org-1", T2)
    assert Organization.objects.get().deleted_at == T2
    assert not _live(Group).exists()
    assert not _live(Membership).exists()


def test_soft_delete_stale_removes_only_rows_not_resynced(repo):
    repo.upsert_group("g-clubs", "clubs", "/clubs", "org-1", T2)
    repo.upsert_membership("alice", "org-1", None, T2)
    repo.soft_delete_stale("org-1", T2)
    assert [g.id for g in _live(Group)] == ["g-clubs"]
    assert [m.group_id for m in _live(Membership)] == [None]


def test_upsert_restores_soft_deleted_membership(repo):
    repo.soft_delete_memberships_by_sub("alice", T2)
    assert not _live(Membership).exists()
    repo.upsert_membership("alice", "org-1", None, T2)
    assert _live(Membership).get().group is None


# --- full sync ----------------------------------------------------------------------


def test_sync_all_fills_an_empty_mirror(admin):
    assert sync_all(admin, DjangoMirrorRepository()) == 1
    assert Organization.objects.get().alias == "jkuat"
    assert {g.path for g in _live(Group)} == {"/clubs", "/clubs/Robotics Club"}
    assert {(m.user_sub, m.group_id) for m in _live(Membership)} == {
        ("alice", None),
        ("alice", "g-robo"),
    }


def test_sync_all_removes_what_keycloak_no_longer_has(admin, repo):
    repo.upsert_organization("org-gone", "Closed", "closed", T1)
    repo.upsert_membership("bob", "org-1", None, T1)
    admin.list_org_group_members.side_effect = lambda org, group: []  # alice left the club

    sync_all(admin, DjangoMirrorRepository())

    assert [o.id for o in _live(Organization)] == ["org-1"]
    assert {(m.user_sub, m.group_id) for m in _live(Membership)} == {("alice", None)}
    assert _live(Group).count() == 2


def test_amt_sync_command(admin):
    out = StringIO()
    call_command("amt_sync", stdout=out)
    assert "Synced 1 organization(s)." in out.getvalue()
    assert Organization.objects.filter(id="org-1").exists()


# --- webhook ------------------------------------------------------------------------

ORG_EVENT = {
    "operationType": "CREATE",
    "resourceType": "ORGANIZATION_MEMBERSHIP",
    "resourcePath": "organizations/org-1/members",
}


def _post(event, secret="hook-secret"):
    headers = {"X-AMT-Webhook-Secret": secret} if secret is not None else {}
    return APIClient().post("/auth/webhook/", event, format="json", headers=headers)


def test_webhook_resyncs_the_organization(admin):
    assert _post(ORG_EVENT).status_code == 204
    assert Organization.objects.get(id="org-1").name == "JKUAT"
    assert _live(Membership).count() == 2


@pytest.mark.parametrize("secret", [None, "", "wrong"])
def test_webhook_rejects_bad_secret(admin, secret):
    assert _post(ORG_EVENT, secret).status_code == 403
    assert not Organization.objects.exists()


def test_webhook_rejects_when_secret_unset(admin, settings):
    settings.AMT_WEBHOOK_SECRET = ""
    assert _post(ORG_EVENT, "").status_code == 403


def test_webhook_malformed_event_is_400(admin):
    response = _post({**ORG_EVENT, "resourcePath": "nonsense"})
    assert response.status_code == 400


def test_webhook_non_object_body_is_400(admin):
    assert _post(["nope"]).status_code == 400


def test_webhook_unrelated_event_is_ignored(admin):
    assert _post({"operationType": "CREATE", "resourceType": "CLIENT"}).status_code == 204


def test_webhook_keycloak_failure_is_502_and_changes_nothing(admin, repo):
    admin.list_org_groups.side_effect = AdminAPIError(500, "boom")
    assert _post(ORG_EVENT).status_code == 502
    assert _live(Group).count() == 2
