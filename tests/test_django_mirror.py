from datetime import datetime, timezone

import pytest
from rest_framework.test import APIClient

from amt_auth import MirrorRepository
from amt_auth.django.models import Group, Membership, Organization
from amt_auth.django.repository import DjangoMirrorRepository

pytestmark = pytest.mark.django_db

T1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 1, 2, tzinfo=timezone.utc)


@pytest.fixture()
def repo():
    repo = DjangoMirrorRepository()
    repo.upsert_organization("org-1", "JKUAT", T1)
    repo.upsert_group("grp-clubs", "clubs", "org-1", None, T1)
    repo.upsert_group("grp-1", "Robotics Club", "org-1", "grp-clubs", T1)
    repo.upsert_membership("user-1", "org-1", None, ["member"], T1)
    repo.upsert_membership("user-1", "org-1", "grp-1", ["lead"], T1)
    return repo


def test_satisfies_protocol():
    assert isinstance(DjangoMirrorRepository(), MirrorRepository)


def test_upsert_is_idempotent_and_updates(repo):
    repo.upsert_organization("org-1", "JKUAT Main", T2)
    repo.upsert_membership("user-1", "org-1", None, ["admin"], T2)
    assert Organization.objects.get().name == "JKUAT Main"
    assert Membership.objects.count() == 2
    assert Membership.objects.get(group=None).roles == ["admin"]


def test_group_kind_comes_from_parent(repo):
    assert Group.objects.get(id="grp-1").kind == "clubs"
    assert Group.objects.get(id="grp-clubs").kind is None


def test_soft_delete_parent_group_takes_children(repo):
    repo.soft_delete_group("grp-clubs", T2)
    assert not Group.objects.filter(deleted_at=None).exists()
    assert Membership.objects.get(group_id="grp-1").deleted_at == T2
    assert Membership.objects.get(group=None).deleted_at is None


def test_soft_delete_org_cascades(repo):
    repo.soft_delete_organization("org-1", T2)
    assert Organization.objects.get().deleted_at == T2
    assert not Group.objects.filter(deleted_at=None).exists()
    assert not Membership.objects.filter(deleted_at=None).exists()


def test_soft_delete_group_removes_its_memberships_only(repo):
    repo.soft_delete_group("grp-1", T2)
    assert Group.objects.get(id="grp-1").deleted_at == T2
    assert Group.objects.get(id="grp-clubs").deleted_at is None
    assert Membership.objects.get(group=None).deleted_at is None
    assert Membership.objects.get(group_id="grp-1").deleted_at == T2


def test_soft_delete_membership_targets_one_row(repo):
    repo.soft_delete_membership("user-1", "org-1", None, T2)
    assert Membership.objects.get(group=None).deleted_at == T2
    assert Membership.objects.get(group_id="grp-1").deleted_at is None


def test_upsert_restores_soft_deleted_membership(repo):
    repo.soft_delete_memberships_by_sub("user-1", T2)
    assert not Membership.objects.filter(deleted_at=None).exists()
    repo.upsert_membership("user-1", "org-1", None, ["member"], T2)
    assert Membership.objects.get(group=None).deleted_at is None


# --- webhook -----------------------------------------------------------------

ORG_EVENT = {"type": "ORG_CREATED", "representation": {"id": "org-2", "name": "UoN"}}


def _post(event, secret="hook-secret"):
    headers = {"X-AMT-Webhook-Secret": secret} if secret is not None else {}
    return APIClient().post("/auth/webhook/", event, format="json", headers=headers)


def test_webhook_writes_event():
    assert _post(ORG_EVENT).status_code == 204
    assert Organization.objects.get(id="org-2").name == "UoN"


@pytest.mark.parametrize("secret", [None, "", "wrong"])
def test_webhook_rejects_bad_secret(secret):
    assert _post(ORG_EVENT, secret).status_code == 403
    assert not Organization.objects.filter(id="org-2").exists()


def test_webhook_rejects_when_secret_unset(settings):
    settings.AMT_WEBHOOK_SECRET = ""
    assert _post(ORG_EVENT, "").status_code == 403


def test_webhook_group_event_records_parent(repo):
    event = {
        "type": "ORG_GROUP_CREATED",
        "representation": {
            "id": "grp-2",
            "name": "Chess Club",
            "organizationId": "org-1",
            "parentId": "grp-clubs",
        },
    }
    assert _post(event).status_code == 204
    assert Group.objects.get(id="grp-2").kind == "clubs"


def test_webhook_malformed_event_is_400():
    response = _post({"type": "ORG_CREATED", "representation": {"id": "org-2"}})
    assert response.status_code == 400


def test_webhook_non_object_body_is_400():
    assert _post(["nope"]).status_code == 400


def test_webhook_unknown_event_is_ignored():
    assert _post({"type": "SOMETHING_ELSE"}).status_code == 204
