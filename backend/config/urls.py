from django.urls import include, path
from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view(["GET"])
def me(request):
    """Who the token says you are. Nothing here touches the database."""
    claims = request.auth
    return Response(
        {
            "sub": claims.sub,
            "email": claims.email,
            "name": claims.name,
            "realm_roles": sorted(claims.realm_roles),
            "organizations": [
                {
                    "id": m.id,
                    "alias": m.alias,
                    "is_admin": m.is_admin,
                    "groups": [{"name": g.name, "kind": g.kind} for g in m.groups],
                }
                for m in claims.memberships
            ],
        }
    )


urlpatterns = [
    path("api/me/", me),
    path("api/auth/", include("amt_auth.django.urls")),
]
