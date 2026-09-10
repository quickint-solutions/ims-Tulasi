"""Create the first administrator, interactively, on a fresh install.

Does nothing once any user exists, so it is safe to run on every start-up.
"""
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand

from accounts.models import Role


class Command(BaseCommand):
    help = "Prompt for the first administrator account if the system has no users yet."

    def handle(self, *args, **options):
        User = get_user_model()
        if User.objects.exists():
            return

        line = "=" * 62
        self.stdout.write(self.style.WARNING(f"\n{line}"))
        self.stdout.write(self.style.WARNING("  FIRST RUN - create your administrator account"))
        self.stdout.write(self.style.WARNING(line))
        self.stdout.write("  Choose a username and password now. You will use these to")
        self.stdout.write("  sign in. The password is not shown as you type - that is")
        self.stdout.write("  normal, just type it and press Enter.")
        self.stdout.write(f"{line}\n")

        call_command("createsuperuser")

        admin = User.objects.filter(is_superuser=True).order_by("id").first()
        if admin is not None and admin.role_id is None:
            admin.role = Role.objects.filter(code="SUPER_ADMIN").first()
            admin.save(update_fields=["role"])
        self.stdout.write(self.style.SUCCESS("\n  Administrator created.\n"))
