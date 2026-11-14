from django.urls import include, path
from rest_framework.response import Response
from rest_framework.views import APIView

from amt_auth.django.permissions import IsOrgMember, has_client_role, has_realm_role


class MeView(APIView):
    def get(self, request):
        return Response({"sub": request.user.id, "email": request.auth.email})


class OrgOnlyView(MeView):
    permission_classes = [IsOrgMember]


class RealmAdminView(MeView):
    permission_classes = [has_realm_role("admin")]


class ClientReadView(MeView):
    permission_classes = [has_client_role("read")]


urlpatterns = [
    path("me/", MeView.as_view()),
    path("org-only/", OrgOnlyView.as_view()),
    path("realm-admin/", RealmAdminView.as_view()),
    path("client-read/", ClientReadView.as_view()),
    path("auth/", include("amt_auth.django.urls")),
]
