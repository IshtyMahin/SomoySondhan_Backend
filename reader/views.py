"""Reader API: authentication, profile and full user CRUD.

Endpoint map (kept compatible with the existing frontend):
  POST   /user/register/                 create an account (emails a confirm link)
  GET    /user/active/<uid>/<token>/     confirm the email address
  POST   /user/login/                    -> {token, user_id, ...}
  POST   /user/logout/                   delete the caller's token
  POST   /user/token/refresh/            rotate the caller's token
  GET    /user/list/                     reader directory (staff only)
  GET    /user/list/<id>/                public profile of one reader
  PATH   /user/list/<id>/                update own account (or staff)
  GET    /user/me/                       the signed-in account
  GET    /user/<id>/is_superuser/        -> {is_superuser} (frontend contract)
  POST   /user/password/change/          change own password
  POST   /user/password/reset/           request a reset email
  POST   /user/password/reset/confirm/   complete the reset
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.db.models import Count, Q
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .authentication import ExpiringTokenAuthentication, issue_token
from .models import Profile
from .permissions import IsSelfOrStaff
from .serializers import (
    LoginSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    ProfileSerializer,
    UserDetailSerializer,
    UserListSerializer,
    UserSerializer,
    UserUpdateSerializer,
)

logger = logging.getLogger(__name__)
User = get_user_model()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def send_confirmation_email(request, user):
    """Email the reader a signed link that activates the account."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    backend = getattr(settings, "BACKEND_URL", "").rstrip("/")
    path = "/user/active/{0}/{1}/".format(uid, token)
    confirm_link = (backend + path) if backend else request.build_absolute_uri(path)

    subject = "Confirm your Somoy Sondhan email"
    body = render_to_string("confirm_email.html", {"confirm_link": confirm_link, "user": user})
    message = EmailMultiAlternatives(subject, "Confirm your email: " + confirm_link, to=[user.email])
    message.attach_alternative(body, "text/html")
    try:
        message.send(fail_silently=False)
    except Exception as exc:  # a mail outage must not break registration
        logger.warning("Could not send confirmation email to %s: %s", user.email, exc)
    return confirm_link


def public_user_payload(user):
    """Only what a reader's review byline needs — never an email address."""
    profile = getattr(user, "profile", None)
    return {
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "display_name": profile.display_name if profile else user.username,
        "role": profile.role if profile else Profile.Role.READER,
        "avatar": profile.avatar.url if profile and profile.avatar else None,
        "date_joined": user.date_joined,
    }


# ---------------------------------------------------------------------------
# registration / activation
# ---------------------------------------------------------------------------
class UserRegistrationAPIView(generics.CreateAPIView):
    """Register a reader. Returns the created account (frontend contract)."""

    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "register"

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        send_confirmation_email(request, user)
        token = issue_token(user)
        return Response(
            {
                "id": user.id,
                "user_id": user.id,
                "token": token.key,
                "username": user.username,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "detail": "Account created successfully.",
            },
            status=status.HTTP_201_CREATED,
        )


def activate(request, uid64, token):
    """Confirm an address, then bounce the reader to the frontend login page."""
    frontend = getattr(settings, "FRONTEND_URL", "").rstrip("/") or ""
    try:
        uid = force_str(urlsafe_base64_decode(uid64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        was_inactive = not user.is_active
        user.is_active = True
        user.save(update_fields=["is_active"])
        profile, _ = Profile.objects.get_or_create(user=user)
        if not profile.email_confirmed:
            profile.email_confirmed = True
            profile.email_confirmed_at = timezone.now()
            profile.save(update_fields=["email_confirmed", "email_confirmed_at"])
        if was_inactive:
            logger.info("Account activated for %s", user.username)
        return redirect((frontend + "/login.html?confirmed=1") if frontend else "/admin/login/")

    return redirect((frontend + "/registration.html?invalid=1") if frontend else "/admin/login/")


# ---------------------------------------------------------------------------
# login / logout / token
# ---------------------------------------------------------------------------
class UserLoginApiView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]

        token = issue_token(user)
        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])
        login(request, user)  # keeps the browsable API working

        profile = getattr(user, "profile", None)
        return Response(
            {
                "token": token.key,
                "user_id": user.id,
                "username": user.username,
                "is_superuser": user.is_superuser,
                "is_staff": user.is_staff,
                "role": profile.role if profile else Profile.Role.READER,
                "expires_in_days": int(getattr(settings, "TOKEN_TTL").days) if getattr(settings, "TOKEN_TTL", None) else None,
            }
        )


class UserLogoutView(APIView):
    """Actually delete the token.

    The old version called `request.user.auth_token.delete()` and then
    `logout(request)`, which raised AttributeError for any caller that was not
    token-authenticated (including anonymous requests).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        deleted = 0
        token = getattr(request, "auth", None)
        if token is not None and hasattr(token, "delete"):
            try:
                token.delete()
                deleted = 1
            except Exception:  # already gone
                deleted = 0
        logout(request)
        return Response({"detail": "Signed out.", "tokens_deleted": deleted})

    def get(self, request):
        # Kept so an old GET-based logout link still works.
        return self.post(request)


class TokenRefreshView(APIView):
    """Rotate the caller's token and extend its life."""

    permission_classes = [IsAuthenticated]
    authentication_classes = [ExpiringTokenAuthentication]

    def post(self, request):
        token = issue_token(request.user)
        return Response(
            {
                "token": token.key,
                "user_id": request.user.id,
                "expires_in_days": int(getattr(settings, "TOKEN_TTL").days) if getattr(settings, "TOKEN_TTL", None) else None,
            }
        )


# ---------------------------------------------------------------------------
# user CRUD
# ---------------------------------------------------------------------------
class UserView(viewsets.ModelViewSet):
    """Full user management.

    * list      — staff only (a reader directory is personal data)
    * retrieve  — public, but limited to non-sensitive fields
    * update    — the account owner or staff
    * destroy   — staff only, and never yourself
    """

    queryset = User.objects.select_related("profile").all()
    authentication_classes = [ExpiringTokenAuthentication]
    filterset_fields = ["is_active", "is_staff", "profile__role"]
    search_fields = ["username", "first_name", "last_name", "email"]
    ordering_fields = ["date_joined", "username", "id"]
    ordering = ["-date_joined"]

    def get_serializer_class(self):
        if self.action == "list":
            return UserListSerializer
        if self.action in {"update", "partial_update"}:
            return UserUpdateSerializer
        if self.action in {"retrieve", "me"}:
            return UserDetailSerializer
        return UserSerializer

    def get_permissions(self):
        if self.action in {"list", "destroy"}:
            return [IsAuthenticated(), IsSelfOrStaff()]
        if self.action in {"update", "partial_update"}:
            return [IsAuthenticated(), IsSelfOrStaff()]
        if self.action in {"me", "change_password", "set_avatar", "delete_me"}:
            return [IsAuthenticated()]
        if self.action in {"block", "unblock", "set_role", "stats"}:
            return [IsAuthenticated(), IsSelfOrStaff()]
        return [AllowAny()]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == "list":
            user = self.request.user
            if not (user.is_staff or user.is_superuser):
                raise PermissionDenied("Only staff can browse the reader directory.")
        return queryset

    def retrieve(self, request, *args, **kwargs):
        """Public profile of one reader.

        The frontend calls this to render review bylines, so it must stay
        anonymous-friendly — but it used to return the email address of every
        user. Signed-in staff still get the full record.
        """
        user = self.get_object()
        if request.user.is_authenticated and (request.user.is_staff or request.user == user):
            return Response(UserDetailSerializer(user, context=self.get_serializer_context()).data)
        return Response(public_user_payload(user))

    # ------------------------------------------------------------------ actions
    @action(detail=False, methods=["get", "patch", "put"])
    def me(self, request):
        """Read or update the signed-in account."""
        if request.method.lower() == "get":
            return Response(UserDetailSerializer(request.user, context={"request": request}).data)
        serializer = UserUpdateSerializer(
            request.user, data=request.data, partial=request.method.lower() == "patch",
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserDetailSerializer(request.user, context={"request": request}).data)

    @action(detail=False, methods=["delete"], url_path="me/delete")
    def delete_me(self, request):
        """Close your own account."""
        user = request.user
        user.is_active = False
        user.save(update_fields=["is_active"])
        from rest_framework.authtoken.models import Token

        Token.objects.filter(user=user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"], url_path="password/change")
    def change_password(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # The old token was revoked, so hand back a fresh one.
        token = issue_token(request.user)
        return Response({"detail": "Password updated.", "token": token.key})

    @action(
        detail=False,
        methods=["post"],
        url_path="me/avatar",
        parser_classes=[MultiPartParser, FormParser, JSONParser],
    )
    def set_avatar(self, request):
        """Upload or clear the avatar on your own profile."""
        profile, _ = Profile.objects.get_or_create(user=request.user)
        avatar = request.data.get("avatar")
        if avatar in (None, "", "null"):
            if profile.avatar:
                profile.avatar.delete(save=False)
            profile.avatar = None
            profile.save(update_fields=["avatar"])
            return Response({"avatar": None})
        if "avatar" not in request.data:
            raise ValidationError({"avatar": "Attach an image file under the key 'avatar'."})
        profile.avatar = request.data["avatar"]
        profile.save(update_fields=["avatar"])
        return Response(ProfileSerializer(profile, context={"request": request}).data)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def block(self, request, pk=None):
        """Suspend a reader without deleting the account (staff only)."""
        if not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied("Only staff can suspend an account.")
        user = self.get_object()
        if user.pk == request.user.pk:
            raise ValidationError({"detail": "You cannot suspend your own account."})
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.is_blocked = True
        profile.save(update_fields=["is_blocked"])
        return Response({"id": user.id, "is_blocked": True})

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def unblock(self, request, pk=None):
        if not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied("Only staff can restore an account.")
        user = self.get_object()
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.is_blocked = False
        profile.save(update_fields=["is_blocked"])
        return Response({"id": user.id, "is_blocked": False})

    @action(detail=True, methods=["post"], url_path="role", permission_classes=[IsAuthenticated])
    def set_role(self, request, pk=None):
        """Promote or demote a reader (staff only)."""
        if not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied("Only staff can change roles.")
        role = request.data.get("role")
        if role not in dict(Profile.Role.choices):
            raise ValidationError({"role": "Choose one of: " + ", ".join(dict(Profile.Role.choices))})
        user = self.get_object()
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.role = role
        profile.save(update_fields=["role"])
        return Response({"id": user.id, "role": role})

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def stats(self, request):
        """Headline numbers for the dashboard (staff only)."""
        if not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied("Only staff can read the dashboard.")
        qs = User.objects.all()
        return Response(
            {
                "total": qs.count(),
                "active": qs.filter(is_active=True).count(),
                "unconfirmed": qs.filter(profile__email_confirmed=False).count(),
                "blocked": qs.filter(profile__is_blocked=True).count(),
                "staff": qs.filter(Q(is_staff=True) | Q(is_superuser=True)).count(),
                "joined_last_7_days": qs.filter(
                    date_joined__gte=timezone.now() - timezone.timedelta(days=7)
                ).count(),
                "by_role": list(
                    Profile.objects.values("role").annotate(count=Count("id")).order_by("-count")
                ),
            }
        )


class UserIsSuperuserView(APIView):
    """GET /user/<pk>/is_superuser/ — exactly the shape the frontend reads.

    This replaces the old `@action(detail=False)` that was wired to a
    `<int:pk>` URL, which meant the route could never be reached.
    """

    permission_classes = [AllowAny]

    def get(self, request, pk=None):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({"error": "User does not exist"}, status=status.HTTP_404_NOT_FOUND)
        profile = getattr(user, "profile", None)
        # The frontend reads `is_superuser` as the gate for the editorial desk,
        # so staff accounts must see it as True too — otherwise editors could
        # never reach add/edit article. The precise flags follow separately.
        return Response(
            {
                "user_id": user.id,
                "is_superuser": bool(user.is_superuser or user.is_staff),
                "is_staff": user.is_staff,
                "is_editor": bool(profile.is_editor) if profile else user.is_superuser or user.is_staff,
            }
        )


# ---------------------------------------------------------------------------
# password reset
# ---------------------------------------------------------------------------
class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "register"

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user is not None:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            frontend = getattr(settings, "FRONTEND_URL", "").rstrip("/")
            link = "{0}/reset.html?uid={1}&token={2}".format(frontend, uid, token)
            body = render_to_string(
                "confirm_email.html",
                {"confirm_link": link, "user": user, "reset": True},
            )
            message = EmailMultiAlternatives(
                "Reset your Somoy Sondhan password", "Reset link: " + link, to=[user.email]
            )
            message.attach_alternative(body, "text/html")
            try:
                message.send(fail_silently=False)
            except Exception as exc:
                logger.warning("Password reset email failed for %s: %s", email, exc)

        # Always the same answer, so this cannot be used to probe addresses.
        return Response({"detail": "If that address is registered, a reset link is on its way."})


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        from rest_framework.authtoken.models import Token

        Token.objects.filter(user=user).delete()
        return Response({"detail": "Password reset. You can sign in now."})
