"""Token authentication that can expire and rotate."""

from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import AuthenticationFailed


class ExpiringTokenAuthentication(TokenAuthentication):
    """DRF token auth with a lifetime.

    The frontend already sends `Authorization: Token <key>`, so the scheme is
    unchanged — tokens simply stop working after `settings.TOKEN_TTL`, and
    `TokenRefreshView` hands out a fresh key.
    """

    keyword = "Token"

    def authenticate_credentials(self, key):
        try:
            token = Token.objects.select_related("user").get(key=key)
        except Token.DoesNotExist:
            raise AuthenticationFailed("Invalid or expired token.")

        if not token.user.is_active:
            raise AuthenticationFailed("This account is inactive.")

        ttl = getattr(settings, "TOKEN_TTL", None)
        if ttl is not None and token.created < timezone.now() - ttl:
            # Expired keys are removed so a stale client cannot keep retrying.
            token.delete()
            raise AuthenticationFailed("Token has expired. Please sign in again.")

        profile = getattr(token.user, "profile", None)
        if profile is not None and profile.is_blocked:
            raise AuthenticationFailed("This account has been suspended.")

        return (token.user, token)


def issue_token(user):
    """Return a usable token for `user`, replacing any expired one.

    Rotating on every login means a leaked key stops working as soon as the
    reader signs in again on another device.
    """
    Token.objects.filter(user=user).delete()
    return Token.objects.create(user=user)
