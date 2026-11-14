from __future__ import annotations

from datetime import datetime

from amt_auth.django.models import Group, Membership, Organization


class DjangoMirrorRepository:
    """Django ORM implementation of `amt_auth.MirrorRepository`."""

    def upsert_organization(self, id: str, name: str, synced_at: datetime) -> None:
        Organization.objects.update_or_create(
            id=id,
            defaults={"name": name, "synced_at": synced_at, "deleted_at": None},
        )

    def soft_delete_organization(self, id: str, synced_at: datetime) -> None:
        # Deleting an organization takes its groups and memberships with it.
        stamp = {"deleted_at": synced_at, "synced_at": synced_at}
        Organization.objects.filter(id=id).update(**stamp)
        Group.objects.filter(organization_id=id).update(**stamp)
        Membership.objects.filter(organization_id=id).update(**stamp)

    def upsert_group(
        self,
        id: str,
        name: str,
        organization_id: str,
        parent_id: str | None,
        synced_at: datetime,
    ) -> None:
        Group.objects.update_or_create(
            id=id,
            defaults={
                "name": name,
                "organization_id": organization_id,
                "parent_id": parent_id,
                "synced_at": synced_at,
                "deleted_at": None,
            },
        )

    def soft_delete_group(self, id: str, synced_at: datetime) -> None:
        stamp = {"deleted_at": synced_at, "synced_at": synced_at}
        Group.objects.filter(id=id).update(**stamp)
        Membership.objects.filter(group_id=id).update(**stamp)
        for child_id in Group.objects.filter(parent_id=id).values_list("id", flat=True):
            self.soft_delete_group(child_id, synced_at)

    def upsert_membership(
        self,
        user_sub: str,
        organization_id: str,
        group_id: str | None,
        roles: list[str],
        synced_at: datetime,
    ) -> None:
        Membership.objects.update_or_create(
            user_sub=user_sub,
            organization_id=organization_id,
            group_id=group_id,
            defaults={"roles": roles, "synced_at": synced_at, "deleted_at": None},
        )

    def soft_delete_membership(
        self,
        user_sub: str,
        organization_id: str,
        group_id: str | None,
        synced_at: datetime,
    ) -> None:
        Membership.objects.filter(
            user_sub=user_sub, organization_id=organization_id, group_id=group_id
        ).update(deleted_at=synced_at, synced_at=synced_at)

    def soft_delete_memberships_by_sub(
        self, user_sub: str, synced_at: datetime
    ) -> None:
        Membership.objects.filter(user_sub=user_sub).update(
            deleted_at=synced_at, synced_at=synced_at
        )
