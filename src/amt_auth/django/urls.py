from django.urls import path

from amt_auth.django.views import (
    KeycloakWebhookView,
    OrganizationCreateView,
    OrganizationInviteView,
)

app_name = "amt_auth"

urlpatterns = [
    path("webhook/", KeycloakWebhookView.as_view(), name="webhook"),
    path("organizations/", OrganizationCreateView.as_view(), name="organization-create"),
    path(
        "organizations/<str:organization_id>/invitations/",
        OrganizationInviteView.as_view(),
        name="organization-invite",
    ),
]
