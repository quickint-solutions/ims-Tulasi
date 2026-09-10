"""Whole-application smoke tests plus the quantity-only guarantee."""
import re

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role
from items.models import Item

User = get_user_model()

# Words that must never appear as a model field name (section 36 / 60).
FORBIDDEN_FIELD_WORDS = [
    "price", "rate", "cost", "amount", "gst", "tax", "vat", "discount", "profit",
    "margin", "currency", "valuation", "mrp", "invoice_value", "sales_value",
    "purchase_value", "total_value",
]

APP_LABELS = ["accounts", "masters", "items", "stock", "labels", "core", "api",
              "integration"]

# Fields whose name contains a forbidden word but carries no monetary meaning.
ALLOWED_FIELDS = {
    "PrinterSetting.margin_mm",   # printable margin on a label, in millimetres
    "ApiKey.rate_limit",          # requests per hour, not a price
}


class NoMoneyAnywhereTests(TestCase):
    """The single most important rule in the brief: quantity only."""

    def test_no_model_field_mentions_money(self):
        offenders = []
        for label in APP_LABELS:
            for model in apps.get_app_config(label).get_models():
                for field in model._meta.get_fields():
                    name = getattr(field, "name", "") or ""
                    for word in FORBIDDEN_FIELD_WORDS:
                        if re.search(rf"(^|_){word}(_|$)", name):
                            key = f"{model.__name__}.{name}"
                            if key not in ALLOWED_FIELDS:
                                offenders.append(key)
        self.assertEqual(offenders, [], f"Monetary fields found: {offenders}")

    def test_no_decimal_field_is_named_like_a_value(self):
        from django.db import models
        offenders = []
        for label in APP_LABELS:
            for model in apps.get_app_config(label).get_models():
                for field in model._meta.get_fields():
                    if isinstance(field, models.DecimalField):
                        name = field.name
                        if any(w in name for w in ("price", "value", "amount", "cost")):
                            offenders.append(f"{model.__name__}.{name}")
        self.assertEqual(offenders, [])


class PageSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_defaults", verbosity=0)
        call_command("seed_demo", verbosity=0)
        cls.admin = User.objects.filter(is_superuser=True).first()
        cls.item = Item.objects.first()

    def setUp(self):
        self.client.force_login(self.admin)

    def test_every_main_page_renders(self):
        item_pk = self.item.pk
        names = [
            ("core:dashboard", []), ("items:list", []), ("items:create", []),
            ("items:detail", [item_pk]), ("items:update", [item_pk]),
            ("items:history", [item_pk]), ("items:import", []),
            ("items:custom_fields", []), ("items:files", []),
            ("masters:category_list", []), ("masters:category_create", []),
            ("masters:warehouse_list", []), ("masters:warehouse_create", []),
            ("masters:rack_list", []), ("masters:column_list", []),
            ("masters:table_list", []), ("masters:location_list", []),
            ("masters:bulk_locations", []), ("masters:uom_list", []),
            ("stock:current", []), ("stock:ledger", []), ("stock:low_stock", []),
            ("stock:out_of_stock", []),
            ("stock:inward_list", []), ("stock:inward_create", []),
            ("stock:outward_list", []), ("stock:outward_create", []),
            ("stock:transfer_list", []), ("stock:transfer_create", []),
            ("stock:adjustment_list", []), ("stock:adjustment_create", []),
            ("stock:opening_list", []), ("stock:opening_create", []),
            ("labels:scanner", []), ("labels:generator", []), ("labels:preview", []),
            ("labels:print_batch", []), ("labels:print_history", []),
            ("labels:printer_list", []), ("labels:template_list", []),
            ("reports:index", []),
            ("accounts:user_list", []), ("accounts:user_create", []),
            ("accounts:role_list", []), ("accounts:audit_log", []),
            ("accounts:profile", []),
            ("integration:erpnext", []), ("integration:sync_log", []),
            ("integration:api_keys", []), ("integration:api_log", []),
            ("core:company_settings", []), ("core:system_settings", []),
            ("core:backup", []),
        ]
        for name, args in names:
            with self.subTest(page=name):
                response = self.client.get(reverse(name, args=args))
                self.assertEqual(response.status_code, 200,
                                 f"{name} returned {response.status_code}")

    def test_every_report_renders_and_exports(self):
        from reports.definitions import REPORTS
        for slug in REPORTS:
            with self.subTest(report=slug):
                page = self.client.get(reverse("reports:run", args=[slug]))
                self.assertEqual(page.status_code, 200)
                excel = self.client.get(reverse("reports:run", args=[slug]),
                                        {"export": "excel"})
                self.assertEqual(excel.status_code, 200)
                self.assertIn("spreadsheetml", excel["Content-Type"])

    def test_report_packs_export(self):
        for name in ("reports:pack_monthly", "reports:pack_yearly"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
            self.assertIn("spreadsheetml", response["Content-Type"])

    def test_item_master_export_has_no_money_columns(self):
        from io import BytesIO
        from openpyxl import load_workbook
        response = self.client.get(reverse("items:export"))
        self.assertEqual(response.status_code, 200)
        wb = load_workbook(BytesIO(response.content))
        headers = [str(c.value or "").lower() for c in wb.active[4]]
        for word in ("price", "rate", "amount", "value", "tax", "gst"):
            self.assertFalse(any(word in h for h in headers),
                             f"'{word}' appeared in the export header row: {headers}")

    def test_global_search_jumps_straight_to_an_exact_barcode(self):
        response = self.client.get(reverse("items:search"), {"q": self.item.barcode_number})
        self.assertRedirects(response, self.item.get_absolute_url())

    def test_health_endpoint(self):
        response = self.client.get(reverse("core:health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")


class PermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_defaults", verbosity=0)
        cls.store_user = User.objects.create_user(
            "storeuser", password="pw12345678", role=Role.objects.get(code="STORE_USER"))
        cls.manager = User.objects.create_user(
            "manager", password="pw12345678", role=Role.objects.get(code="STORE_MANAGER"))

    def test_store_user_cannot_open_user_administration(self):
        self.client.force_login(self.store_user)
        self.assertEqual(self.client.get(reverse("accounts:user_list")).status_code, 403)

    def test_store_user_cannot_open_backup(self):
        self.client.force_login(self.store_user)
        self.assertEqual(self.client.get(reverse("core:backup")).status_code, 403)

    def test_store_user_can_reach_the_scanner(self):
        self.client.force_login(self.store_user)
        self.assertEqual(self.client.get(reverse("labels:scanner")).status_code, 200)

    def test_manager_can_open_transactions_but_not_users(self):
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("stock:inward_create")).status_code, 200)
        self.assertEqual(self.client.get(reverse("accounts:user_list")).status_code, 403)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("items:list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])


class BackupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_defaults", verbosity=0)
        call_command("seed_demo", verbosity=0)

    def test_backup_round_trip(self):
        from core import backup as service
        from core.models import Backup
        admin = User.objects.filter(is_superuser=True).first()
        row = service.create_backup(include_media=False, user=admin)
        self.assertGreater(row.size_bytes, 0)

        item_count = Item.objects.count()
        original_name = Item.objects.get(item_number="SP-002").name
        Item.objects.filter(item_number="SP-002").update(name="EDITED AFTER BACKUP")
        Item.objects.create(item_number="TMP-999", name="Created after backup",
                            category=Item.objects.first().category,
                            uom=Item.objects.first().uom)
        self.assertEqual(Item.objects.count(), item_count + 1)

        with open(row.path, "rb") as fh:
            manifest = service.restore_backup(fh, restore_media=False, user=admin)

        self.assertIn("record_counts", manifest)
        self.assertEqual(Item.objects.count(), item_count)
        self.assertEqual(Item.objects.get(item_number="SP-002").name, original_name)
        self.assertFalse(Item.objects.filter(item_number="TMP-999").exists())
        # Stock history survived the round trip.
        from stock.models import StockMovement
        self.assertGreater(StockMovement.objects.count(), 0)
