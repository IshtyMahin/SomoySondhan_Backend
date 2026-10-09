"""Create Profile rows for accounts that existed before the model did.

Run once after migrating:

    python manage.py backfill_profiles

Safe to run repeatedly: existing profiles are left untouched unless
`--sync-roles` is passed, which copies is_superuser/is_staff onto Profile.role.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from reader.models import Profile

User = get_user_model()


class Command(BaseCommand):
    help = "Create missing Profile rows for existing users."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sync-roles",
            action="store_true",
            help="Also copy is_superuser/is_staff onto Profile.role.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        created = 0
        for user in User.objects.all().iterator():
            _, was_created = Profile.objects.get_or_create(user=user)
            if was_created:
                created += 1

        self.stdout.write(self.style.SUCCESS("Profiles created: {0}".format(created)))

        if options["sync_roles"]:
            admins = Profile.objects.filter(user__is_superuser=True).exclude(role=Profile.Role.ADMIN)
            editors = (
                Profile.objects.filter(user__is_staff=True)
                .exclude(user__is_superuser=True)
                .exclude(role=Profile.Role.EDITOR)
            )
            admin_count = admins.update(role=Profile.Role.ADMIN)
            editor_count = editors.update(role=Profile.Role.EDITOR)
            self.stdout.write(
                self.style.SUCCESS(
                    "Roles synced — admins: {0}, editors: {1}".format(admin_count, editor_count)
                )
            )

        total = Profile.objects.count()
        active = Profile.objects.filter(email_confirmed=True).count()
        self.stdout.write("Total profiles: {0} (confirmed: {1})".format(total, active))
