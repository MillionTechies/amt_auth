from django.core.management.base import BaseCommand
from django.db import transaction

from amt_auth.core.sync import sync_all
from amt_auth.django.authentication import get_auth_service
from amt_auth.django.repository import DjangoMirrorRepository


class Command(BaseCommand):
    help = "Make the mirror tables match Keycloak's organizations, groups and members."

    def handle(self, *args, **options):
        with transaction.atomic():
            count = sync_all(get_auth_service().admin, DjangoMirrorRepository())
        self.stdout.write(self.style.SUCCESS(f"Synced {count} organization(s)."))
