"""Reader routes.

Order matters: the explicit paths for `active/`, `login/`, `me/` and
`<pk>/is_superuser/` are declared before the router so they win over the
router's own `list/<pk>/` pattern.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    PasswordResetConfirmView,
    PasswordResetRequestView,
    TokenRefreshView,
    UserIsSuperuserView,
    UserLoginApiView,
    UserLogoutView,
    UserRegistrationAPIView,
    UserView,
    activate,
)

router = DefaultRouter()
router.register("list", UserView, basename="user")

urlpatterns = [
    # authentication
    path("register/", UserRegistrationAPIView.as_view(), name="register"),
    path("login/", UserLoginApiView.as_view(), name="login"),
    path("logout/", UserLogoutView.as_view(), name="logout"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("active/<str:uid64>/<str:token>/", activate, name="activate"),

    # password reset
    path("password/reset/", PasswordResetRequestView.as_view(), name="password-reset"),
    path("password/reset/confirm/", PasswordResetConfirmView.as_view(), name="password-reset-confirm"),

    # the frontend's superuser check (was unreachable before)
    path("<int:pk>/is_superuser/", UserIsSuperuserView.as_view(), name="is-superuser"),

    # Non-detail ViewSet actions. The router registers the ViewSet under
    # `list/`, which would otherwise bury these at `/user/list/me/` etc. The
    # documented contract (and the frontend/tests) expects them at the top
    # level, so they are wired explicitly here.
    path("me/", UserView.as_view({"get": "me", "patch": "me", "put": "me"}), name="user-me"),
    path("me/delete/", UserView.as_view({"delete": "delete_me"}), name="user-me-delete"),
    path(
        "me/avatar/",
        UserView.as_view({"post": "set_avatar"}),
        name="user-me-avatar",
    ),
    path(
        "password/change/",
        UserView.as_view({"post": "change_password"}),
        name="user-password-change",
    ),
    path("stats/", UserView.as_view({"get": "stats"}), name="user-stats"),

    # user CRUD (list/, list/<pk>/, me/, me/avatar/, password/change/, stats/, ...)
    path("", include(router.urls)),
]
