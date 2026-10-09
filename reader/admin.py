"""Admin for reader accounts.

The stock User admin is unregistered and replaced with one that shows the
Profile inline, so staff can confirm addresses, set roles and suspend accounts
from a single screen.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User

from .models import Profile

# The stock auth admin already registers User; drop it so the subclass below can
# take its place without raising AlreadyRegistered.
admin.site.unregister(User)


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = "Profile"
    fk_name = "user"
    fields = ("role", "bio", "avatar", "location", "website",
              "email_confirmed", "email_confirmed_at", "is_blocked")


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    inlines = [ProfileInline]
    list_display = ("id", "username", "email", "full_name", "role_name",
                    "is_active", "is_staff", "date_joined")
    list_filter = ("is_active", "is_staff", "is_superuser", "profile__role", "profile__is_blocked")
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("-date_joined",)
    actions = ["activate_accounts", "deactivate_accounts", "block_readers", "unblock_readers"]

    @admin.display(description="name")
    def full_name(self, obj):
        return obj.get_full_name() or "—"

    @admin.display(description="role")
    def role_name(self, obj):
        profile = getattr(obj, "profile", None)
        return profile.get_role_display() if profile else "—"

    @admin.action(description="Activate selected accounts")
    def activate_accounts(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, "{0} account(s) activated.".format(updated))

    @admin.action(description="Deactivate selected accounts")
    def deactivate_accounts(self, request, queryset):
        updated = queryset.exclude(pk=request.user.pk).update(is_active=False)
        self.message_user(request, "{0} account(s) deactivated.".format(updated))

    @admin.action(description="Suspend (block) selected readers")
    def block_readers(self, request, queryset):
        updated = Profile.objects.filter(user__in=queryset).update(is_blocked=True)
        self.message_user(request, "{0} reader(s) suspended.".format(updated))

    @admin.action(description="Restore selected readers")
    def unblock_readers(self, request, queryset):
        updated = Profile.objects.filter(user__in=queryset).update(is_blocked=False)
        self.message_user(request, "{0} reader(s) restored.".format(updated))


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "role", "email_confirmed", "is_blocked", "created_at")
    list_filter = ("role", "email_confirmed", "is_blocked")
    search_fields = ("user__username", "user__email", "bio")
    readonly_fields = ("created_at", "updated_at", "email_confirmed_at")
    autocomplete_fields = ("user",)
