"""Reset inventory/module data while preserving access and integration setup."""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from accounts.models import AuditLog, User
from api.models import ApiLog
from core.backup import create_backup
from integration.models import SyncLog
from items.models import CustomFieldDefinition, Item, ItemCategory, ItemDocument, ItemImage
from labels.models import LabelPrintLog
from masters.models import Location, Rack, RackColumn, RackTable, Warehouse
from stock.models import (
    AdjustmentDocument,
    AdjustmentItem,
    InwardDocument,
    InwardItem,
    OpeningStockDocument,
    OpeningStockItem,
    OutwardDocument,
    OutwardItem,
    StockBalance,
    StockMovement,
    TransferDocument,
    TransferItem,
)


DELETE_MODELS = [
    ("Label print history", LabelPrintLog),
    ("API request logs", ApiLog),
    ("ERPNext sync logs", SyncLog),
    ("Audit logs", AuditLog),
    ("Transfer lines", TransferItem),
    ("Transfer documents", TransferDocument),
    ("Adjustment lines", AdjustmentItem),
    ("Adjustment documents", AdjustmentDocument),
    ("Opening stock lines", OpeningStockItem),
    ("Opening stock documents", OpeningStockDocument),
    ("Outward lines", OutwardItem),
    ("Outward documents", OutwardDocument),
    ("Inward lines", InwardItem),
    ("Inward documents", InwardDocument),
    ("Stock balances / current stock", StockBalance),
    ("Stock ledger / movements", StockMovement),
    ("Item documents", ItemDocument),
    ("Item images", ItemImage),
    ("Items / barcode records", Item),
    ("Custom item fields", CustomFieldDefinition),
    ("Locations", Location),
    ("Tables", RackTable),
    ("Columns", RackColumn),
    ("Racks", Rack),
    ("Warehouses", Warehouse),
    ("Item categories", ItemCategory),
]


class Command(BaseCommand):
    help = (
        "Delete inventory, stock, warehouse, label-log, report-source and module data "
        "while preserving users, roles, permissions, settings, API keys and ERPNext settings."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show counts only. No backup or delete is performed.",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually delete the rows. A database backup is created first.",
        )
        parser.add_argument(
            "--no-media",
            action="store_true",
            help="Do not include uploaded media in the pre-reset backup.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"] or not options["confirm"]
        missing_tables = self._missing_tables()
        if missing_tables:
            missing = ", ".join(missing_tables)
            raise CommandError(
                "The selected database is not migrated or is not the expected app database. "
                f"Missing table(s): {missing}"
            )

        counts = self._counts()

        self.stdout.write("Business/module data selected for reset:")
        for label, count in counts:
            self.stdout.write(f"  {label}: {count}")

        if dry_run:
            total = sum(count for _label, count in counts)
            self.stdout.write(self.style.WARNING(
                f"Dry run only. {total} row(s) would be deleted. "
                "Run again with --confirm to create a backup and reset data."
            ))
            return

        if not options["confirm"]:
            raise CommandError("Refusing to delete without --confirm.")

        backup = create_backup(
            include_media=not options["no_media"],
            notes="Automatic backup before reset_business_data",
        )
        self.stdout.write(self.style.SUCCESS(
            f"Backup created before reset: {backup.filename} ({backup.size_display})"
        ))

        with transaction.atomic():
            cleared_defaults = User.objects.exclude(default_warehouse=None).update(
                default_warehouse=None
            )
            for user in User.objects.prefetch_related("allowed_warehouses"):
                user.allowed_warehouses.clear()
            if cleared_defaults:
                self.stdout.write(
                    f"Cleared default warehouse from {cleared_defaults} user(s)."
                )

            for label, model in DELETE_MODELS:
                deleted, _details = model.objects.all().delete()
                self.stdout.write(f"Deleted {label}: {deleted}")

        self.stdout.write(self.style.SUCCESS(
            "Reset complete. Users, roles, permissions, company/system settings, "
            "label/printer templates, API keys and ERPNext settings were preserved."
        ))

    def _counts(self):
        return [(label, model.objects.count()) for label, model in DELETE_MODELS]

    def _missing_tables(self):
        existing = set(connection.introspection.table_names())
        expected = {model._meta.db_table for _label, model in DELETE_MODELS}
        return sorted(expected - existing)
