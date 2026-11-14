from __future__ import annotations

import hmac

from django.conf import settings
from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from amt_auth.core.sync import consume_event
from amt_auth.django import authentication
from amt_auth.django.permissions import IsOrgAdmin, IsPlatformAdmin
from amt_auth.django.repository import DjangoMirrorRepository
from amt_auth.exceptions import AdminAPIError, SyncError

WEBHOOK_SECRET_HEADER = "X-AMT-Webhook-Secret"


class KeycloakWebhookView(APIView):
    """Receives Keycloak org events and writes them to the mirror tables.

    The caller must send `settings.AMT_WEBHOOK_SECRET` in the
    `X-AMT-Webhook-Secret` header.
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        secret = settings.AMT_WEBHOOK_SECRET
        sent = request.headers.get(WEBHOOK_SECRET_HEADER, "")
        if not secret or not hmac.compare_digest(sent.encode(), secret.encode()):
            raise PermissionDenied("Invalid webhook secret.")
        if not isinstance(request.data, dict):
            raise ValidationError("Event must be a JSON object.")
        try:
            with transaction.atomic():
                consume_event(request.data, DjangoMirrorRepository())
        except SyncError as exc:
            raise ValidationError(str(exc)) from exc
        return Response(status=204)


# ---------------------------------------------------------------------------
# Onboarding: admins set up organizations and bring users into them.
# These call Keycloak; the mirror tables catch up through the webhook.
# ---------------------------------------------------------------------------


def _keycloak_error(exc: AdminAPIError) -> APIException:
    """A Keycloak conflict is the caller's problem (409); anything else is a 502."""
    error = APIException(
        "Already exists." if exc.status_code == 409 else "Keycloak request failed."
    )
    error.status_code = 409 if exc.status_code == 409 else 502
    return error


class OrganizationSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    domains = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )


class InviteSerializer(serializers.Serializer):
    email = serializers.EmailField()
    first_name = serializers.CharField(required=False, default="", allow_blank=True)
    last_name = serializers.CharField(required=False, default="", allow_blank=True)


class OrganizationCreateView(APIView):
    """Platform admins create a new organization."""

    permission_classes = [IsPlatformAdmin]

    def post(self, request):
        data = OrganizationSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        admin = authentication.get_auth_service().admin
        try:
            org_id = admin.create_organization(**data.validated_data)
        except AdminAPIError as exc:
            raise _keycloak_error(exc) from exc
        return Response({"id": org_id, "name": data.validated_data["name"]}, status=201)


class OrganizationInviteView(APIView):
    """An organization's admin invites a user to register and join it."""

    permission_classes = [IsOrgAdmin | IsPlatformAdmin]

    def post(self, request, organization_id: str):
        data = InviteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        admin = authentication.get_auth_service().admin
        try:
            admin.invite_org_member(organization_id, **data.validated_data)
        except AdminAPIError as exc:
            raise _keycloak_error(exc) from exc
        return Response(status=204)
