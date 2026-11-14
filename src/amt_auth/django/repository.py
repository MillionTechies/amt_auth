from __future__ import annotations

from datetime import datetime

from amt_auth.django.models import Group, Membership, Organization


class DjangoMirrorRepository:
    """Django ORM implementation of `amt_auth.MirrorRepository`."""

    def upsert_organization(
        self, id: str, name: str, alias: str, synced_at: datetime
    ) -> None:
        Organization.objects.update_or_create(
            id=id,
            defaults={
                "name": name,
                "alias": alias,
                "synced_at": synced_at,
                "deleted_at": None,
            },
        )

    def soft_delete_organization(self, id: str, synced_at: datetime) -> None:
        # Deleting an organization takes its groups and memberships with it.
        Organization.objects.filter(id=id).update(deleted_at=synced_at)
        Group.objects.filter(organization_id=id).update(deleted_at=synced_at)
        Membership.objects.filter(organization_id=id).update(deleted_at=synced_at)

    def upsert_group(
        self, id: str, name: str, path: str, organization_id: str, synced_at: datetime
    ) -> None:
        Group.objects.update_or_create(
            id=id,
            defaults={
                "name": name,
                "path": path,
                "organization_id": organization_id,
                "synced_at": synced_at,
                "deleted_at": None,
            },
        )

    def upsert_membership(
        self,
        user_sub: str,
        organization_id: str,
        group_id: str | None,
        synced_at: datetime,
    ) -> None:
        Membership.objects.update_or_create(
            user_sub=user_sub,
            organization_id=organization_id,
            group_id=group_id,
            defaults={"synced_at": synced_at, "deleted_at": None},
        )

    def soft_delete_stale(self, organization_id: str, synced_at: datetime) -> None:
        for model in (Group, Membership):
            model.objects.filter(
                organization_id=organization_id,
                synced_at__lt=synced_at,
                deleted_at=None,
            ).update(deleted_at=synced_at)

    def soft_delete_stale_organizations(self, synced_at: datetime) -> None:
        stale = Organization.objects.filter(synced_at__lt=synced_at, deleted_at=None)
        for org_id in list(stale.values_list("id", flat=True)):
            self.soft_delete_organization(org_id, synced_at)

    def soft_delete_memberships_by_sub(
        self, user_sub: str, synced_at: datetime
    ) -> None:
        Membership.objects.filter(user_sub=user_sub).update(deleted_at=synced_at)
