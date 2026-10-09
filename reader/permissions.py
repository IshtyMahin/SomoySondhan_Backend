"""Permission classes shared by the reader and article APIs."""

from rest_framework import permissions


class IsSelfOrStaff(permissions.BasePermission):
    """A reader may read/update only their own record; staff may do anything."""

    message = "You can only manage your own account."

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_staff or user.is_superuser:
            return True
        target = getattr(obj, "user", obj)
        return target == user


class IsEditorOrReadOnly(permissions.BasePermission):
    """Anyone may read published content; only editors may change it.

    This is the permission that was missing before: previously any anonymous
    visitor could create, edit or delete articles and categories.
    """

    message = "Editorial access is required for this action."

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser or user.is_staff:
            return True
        profile = getattr(user, "profile", None)
        return bool(profile and profile.is_editor)


class IsOwnerOrEditor(permissions.BasePermission):
    """The author of a record (or an editor) may modify it."""

    message = "You can only change your own content."

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser or user.is_staff:
            return True
        profile = getattr(user, "profile", None)
        if profile and profile.is_editor:
            return True
        return getattr(obj, "user", None) == user or getattr(obj, "author", None) == user
