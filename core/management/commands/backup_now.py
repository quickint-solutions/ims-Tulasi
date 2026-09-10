"""Create a backup from the command line - for cron or a scheduled container."""
from django.core.management.base import BaseCommand

from core.backup import create_backup
from core.models import Backup


class Command(BaseCommand):
    help = "Create a database (and optionally media) backup."

    def add_arguments(self, parser):
        parser.add_argument("--no-media", action="store_true",
                            help="Database only - a much smaller file.")
        parser.add_argument("--scheduled", action="store_true",
                            help="Tag the backup as scheduled rather than manual.")
        parser.add_argument("--keep", type=int, default=30,
                            help="Delete scheduled backups older than the newest N.")

    def handle(self, *args, **options):
        row = create_backup(
            include_media=not options["no_media"],
            kind=Backup.Kind.SCHEDULED if options["scheduled"] else Backup.Kind.MANUAL,
            notes="Created by backup_now")
        self.stdout.write(self.style.SUCCESS(
            f"Created {row.filename} ({row.size_display})"))

        keep = options["keep"]
        if keep and options["scheduled"]:
            from core.backup import delete_backup
            old = Backup.objects.filter(kind=Backup.Kind.SCHEDULED)[keep:]
            for backup in old:
                delete_backup(backup)
            if old:
                self.stdout.write(f"Pruned {len(old)} old scheduled backup(s).")
