"""Reader accounts: a Profile that extends Django's built-in User.

The project deliberately keeps `django.contrib.auth.models.User` (all existing
accounts live in `auth_user`), so everything extra hangs off a OneToOne Profile.
That preserves every current user, article and review.
"""

from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.text import slugify


def avatar_upload_to(instance, filename):
    """Keep avatars in their own folder, named after the user."""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    return "avatars/user_{0}/{1}.{2}".format(instance.user_id, slugify(instance.user.username), extension)


class Profile(models.Model):
    """Extra reader/editor data. One row per user, created automatically."""

    class Role(models.TextChoices):
        READER = "reader", "Reader"
        AUTHOR = "author", "Author"
        EDITOR = "editor", "Editor"
        ADMIN = "admin", "Administrator"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")

    role = models.CharField(max_length=16, choices=Role.choices, default=Role.READER)
    bio = models.TextField(max_length=500, blank=True)
    avatar = models.ImageField(upload_to=avatar_upload_to, blank=True, null=True)
    location = models.CharField(max_length=120, blank=True)
    website = models.URLField(max_length=200, blank=True)

    # Registration confirmation (the old code toggled `is_active` and had no
    # way to tell a confirmed account from one that never received the mail).
    email_confirmed = models.BooleanField(default=False)
    email_confirmed_at = models.DateTimeField(null=True, blank=True)

    # A soft switch: staff can silence a reader without deleting the account.
    is_blocked = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["role"])]

    def __str__(self):
        return "Profile<{0}>".format(self.user.username)

    @property
    def display_name(self):
        full = self.user.get_full_name().strip()
        return full or self.user.username

    @property
    def is_editor(self):
        """True when this account may publish and moderate.

        Superusers and staff always count, so the people already running the
        site keep their access without any data change. Any editorial role
        (author, editor, admin) also counts — only plain readers are excluded.
        """
        return bool(
            self.user.is_superuser
            or self.user.is_staff
            or self.role in {self.Role.AUTHOR, self.Role.EDITOR, self.Role.ADMIN}
        )


@receiver(post_save, sender=User)
def ensure_profile(sender, instance, created, **kwargs):
    """Every user gets a Profile — including the ones that already exist.

    The management command `python manage.py backfill_profiles` uses the same
    helper to create rows for accounts made before this model existed.
    """
    Profile.objects.get_or_create(user=instance)


def sync_role_from_user(profile):
    """Keep Profile.role consistent with the flags Django already uses."""
    if profile.user.is_superuser and profile.role != Profile.Role.ADMIN:
        profile.role = Profile.Role.ADMIN
        profile.save(update_fields=["role"])
    elif profile.user.is_staff and profile.role == Profile.Role.READER:
        profile.role = Profile.Role.EDITOR
        profile.save(update_fields=["role"])
