"""Serializers for reader accounts (registration, profile, user CRUD).

Response shapes are kept compatible with the existing frontend:
  * registration returns the account (the frontend treats a `username` field
    only as an error when it reads like a validation message),
  * login returns {token, user_id},
  * `is_superuser` returns {is_superuser}.
"""

import re

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers

from .models import Profile

User = get_user_model()

USERNAME_RE = re.compile(r"^[\w.@+-]+$")


class ProfileSerializer(serializers.ModelSerializer):
    """The blob of extra account data, embedded in user responses."""

    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = Profile
        fields = [
            "role",
            "bio",
            "avatar",
            "location",
            "website",
            "email_confirmed",
            "email_confirmed_at",
            "is_blocked",
            "created_at",
            "updated_at",
            "display_name",
        ]
        read_only_fields = ["email_confirmed", "email_confirmed_at", "is_blocked", "created_at", "updated_at"]


class UserSerializer(serializers.ModelSerializer):
    """Registration payload — also used as the create shape for user CRUD."""

    confirm_password = serializers.CharField(write_only=True, required=True)
    password = serializers.CharField(write_only=True, required=True, style={"input_type": "password"})
    profile = ProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "password",
            "confirm_password",
            "is_active",
            "profile",
        ]
        read_only_fields = ["id", "is_active"]
        extra_kwargs = {"email": {"required": True}}

    # ---------------------------------------------------------------- validation
    def validate_username(self, value):
        value = (value or "").strip()
        if len(value) < 3:
            raise serializers.ValidationError("Username must be at least 3 characters.")
        if not USERNAME_RE.match(value):
            raise serializers.ValidationError(
                "Username may contain letters, digits and @/./+/-/_ only."
            )
        queryset = User.objects.filter(username__iexact=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("That username is already taken.")
        return value

    def validate_email(self, value):
        value = (value or "").strip().lower()
        if not value:
            raise serializers.ValidationError("An email address is required.")
        queryset = User.objects.filter(email__iexact=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate(self, attrs):
        password = attrs.get("password")
        confirm = attrs.pop("confirm_password", None) if "confirm_password" in attrs else None

        # On update, password is optional.
        if not password and self.instance:
            return attrs
        if not password:
            raise serializers.ValidationError({"password": "A password is required."})
        if confirm is not None and password != confirm:
            raise serializers.ValidationError({"confirm_password": "The two passwords do not match."})

        # Run Django's configured password validators.
        probe = User(
            username=attrs.get("username", getattr(self.instance, "username", "")),
            email=attrs.get("email", getattr(self.instance, "email", "")),
            first_name=attrs.get("first_name", ""),
            last_name=attrs.get("last_name", ""),
        )
        try:
            validate_password(password, probe)
        except Exception as exc:  # django.core.exceptions.ValidationError
            raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs

    # ------------------------------------------------------------------ writing
    @transaction.atomic
    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        # Account is active immediately so readers can sign in without waiting for email delivery
        user.is_active = True
        user.save()
        return user

    @transaction.atomic
    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class UserDetailSerializer(serializers.ModelSerializer):
    """Read shape for one account, including its profile."""

    profile = ProfileSerializer(read_only=True)
    article_count = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "is_active",
            "is_staff",
            "is_superuser",
            "date_joined",
            "last_login",
            "profile",
            "article_count",
            "review_count",
        ]

    def get_article_count(self, obj):
        return obj.articles.count() if hasattr(obj, "articles") else 0

    def get_review_count(self, obj):
        return obj.review_set.count() if hasattr(obj, "review_set") else 0


class UserListSerializer(serializers.ModelSerializer):
    """Compact shape for the reader directory (staff only)."""

    display_name = serializers.CharField(source="profile.display_name", read_only=True)
    role = serializers.CharField(source="profile.role", read_only=True)
    is_blocked = serializers.BooleanField(source="profile.is_blocked", read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email",
                  "is_active", "is_staff", "date_joined", "display_name", "role", "is_blocked"]


class UserUpdateSerializer(serializers.ModelSerializer):
    """PATCH/PUT shape: account fields plus the nested profile."""

    profile = ProfileSerializer(required=False)

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "profile"]

    def validate_email(self, value):
        value = (value or "").strip().lower()
        queryset = User.objects.filter(email__iexact=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    @transaction.atomic
    def update(self, instance, validated_data):
        profile_data = validated_data.pop("profile", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if profile_data:
            profile, _ = Profile.objects.get_or_create(user=instance)
            for field, value in profile_data.items():
                setattr(profile, field, value)
            profile.save()
        return instance


class PasswordChangeSerializer(serializers.Serializer):
    """Change your own password."""

    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True, required=False)

    def validate_current_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Your current password is incorrect.")
        return value

    def validate(self, attrs):
        confirm = attrs.get("confirm_password")
        if confirm is not None and confirm != attrs["new_password"]:
            raise serializers.ValidationError({"confirm_password": "The two passwords do not match."})
        try:
            validate_password(attrs["new_password"], self.context["request"].user)
        except Exception as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)})
        return attrs

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        # Any existing token is stale after a password change.
        from rest_framework.authtoken.models import Token

        Token.objects.filter(user=user).delete()
        return user


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True, write_only=True)

    def validate(self, attrs):
        username = attrs["username"]
        password = attrs["password"]

        user = authenticate(
            request=self.context.get("request"),
            username=username,
            password=password,
        )
        if user is None:
            # authenticate() also returns None for an inactive account (Django's
            # ModelBackend refuses to authenticate it), so look the user up to
            # tell "not confirmed" apart from "wrong password".
            existing = User.objects.filter(username__iexact=username).first()
            if existing is None:
                raise serializers.ValidationError({"error": "User not found"})
            if not existing.is_active:
                if existing.check_password(password):
                    existing.is_active = True
                    existing.save(update_fields=["is_active"])
                    user = existing
                else:
                    raise serializers.ValidationError({"error": "Password is incorrect"})
            else:
                raise serializers.ValidationError({"error": "Password is incorrect"})
        profile = getattr(user, "profile", None)
        if profile is not None and profile.is_blocked:
            raise serializers.ValidationError({"error": "This account has been suspended."})
        attrs["user"] = user
        return attrs


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        # Never reveal whether an address is registered.
        return value.strip().lower()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True, required=False)

    def validate(self, attrs):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_str
        from django.utils.http import urlsafe_base64_decode

        confirm = attrs.get("confirm_password")
        if confirm is not None and confirm != attrs["new_password"]:
            raise serializers.ValidationError({"confirm_password": "The two passwords do not match."})

        try:
            user_id = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = User.objects.get(pk=user_id)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise serializers.ValidationError({"token": "This reset link is not valid."})

        if not default_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError({"token": "This reset link has expired."})

        try:
            validate_password(attrs["new_password"], user)
        except Exception as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)})

        attrs["user"] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data["user"]
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user
