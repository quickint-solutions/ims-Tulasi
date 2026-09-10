from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook

from masters.models import ItemCategory, UnitOfMeasure, Warehouse
from stock.models import OpeningStockDocument, StockBalance
from .importexport import import_items, read_rows
from .models import Item

User = get_user_model()
D = Decimal


class ItemMasterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_defaults", verbosity=0)
        cls.admin = User.objects.create_superuser("admin2", "a@b.com", "pw12345678")
        cls.category = ItemCategory.objects.first()
        cls.uom = UnitOfMeasure.objects.get(code="NOS")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_barcode_defaults_to_the_item_number(self):
        item = Item.objects.create(item_number="sp-900", name="Test",
                                   category=self.category, uom=self.uom)
        self.assertEqual(item.item_number, "SP-900")   # normalised to upper case
        self.assertEqual(item.barcode_number, "SP-900")

    def test_every_item_gets_a_unique_qr_token(self):
        a = Item.objects.create(item_number="SP-901", name="A", category=self.category,
                                uom=self.uom)
        b = Item.objects.create(item_number="SP-902", name="B", category=self.category,
                                uom=self.uom)
        self.assertNotEqual(a.qr_token, b.qr_token)

    def test_duplicate_item_number_is_rejected_by_the_form(self):
        Item.objects.create(item_number="SP-903", name="A", category=self.category,
                            uom=self.uom)
        response = self.client.post(reverse("items:create"), {
            "item_number": "SP-903", "name": "Duplicate", "category": self.category.pk,
            "uom": self.uom.pk, "minimum_stock": 0, "maximum_stock": 0, "reorder_level": 0,
            "images-TOTAL_FORMS": 0, "images-INITIAL_FORMS": 0,
            "docs-TOTAL_FORMS": 0, "docs-INITIAL_FORMS": 0,
        })
        self.assertContains(response, "already exists")

    def test_duplicate_barcode_is_rejected(self):
        Item.objects.create(item_number="SP-904", name="A", category=self.category,
                            uom=self.uom, barcode_number="SHARED-1")
        response = self.client.post(reverse("items:create"), {
            "item_number": "SP-905", "name": "B", "category": self.category.pk,
            "uom": self.uom.pk, "barcode_number": "SHARED-1",
            "minimum_stock": 0, "maximum_stock": 0, "reorder_level": 0,
            "images-TOTAL_FORMS": 0, "images-INITIAL_FORMS": 0,
            "docs-TOTAL_FORMS": 0, "docs-INITIAL_FORMS": 0,
        })
        self.assertContains(response, "already assigned")

    def test_free_form_part_numbers_are_accepted(self):
        for number in ("SP-001", "PUMP-001", "VALVE-015", "BOILER-FD-001", "A1/B2"):
            item = Item.objects.create(item_number=number, name=number,
                                       category=self.category, uom=self.uom)
            self.assertEqual(item.item_number, number.upper())

    def test_sub_category_must_belong_to_the_category(self):
        other = ItemCategory.objects.exclude(pk=self.category.pk).first()
        sub = ItemCategory.objects.create(name="Impellers", parent=other)
        response = self.client.post(reverse("items:create"), {
            "item_number": "SP-906", "name": "X", "category": self.category.pk,
            "sub_category": sub.pk, "uom": self.uom.pk,
            "minimum_stock": 0, "maximum_stock": 0, "reorder_level": 0,
            "images-TOTAL_FORMS": 0, "images-INITIAL_FORMS": 0,
            "docs-TOTAL_FORMS": 0, "docs-INITIAL_FORMS": 0,
        })
        self.assertContains(response, "is not a sub-category")


class ImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_defaults", verbosity=0)
        cls.admin = User.objects.create_superuser("admin3", "a@b.com", "pw12345678")
        cls.warehouse = Warehouse.objects.create(code="MAIN", name="Main Warehouse")

    def _sheet(self, rows):
        wb = Workbook()
        ws = wb.active
        ws.append(["Item Number", "Item Name", "Category", "Make", "Material", "UOM",
                   "Reorder Level", "Warehouse", "Rack", "Column", "Table",
                   "Opening Quantity"])
        for row in rows:
            ws.append(row)
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        buf.name = "items.xlsx"
        return buf

    def test_import_creates_items_categories_and_locations(self):
        sheet = self._sheet([
            ["IMP-001", "IMPORTED PUMP SEAL", "Pump Spares", "KSB", "SS 316", "NOS", 5,
             "Main Warehouse", "RACK-A", "C-01", "T-01", 30],
            ["IMP-002", "IMPORTED BEARING", "Bearings", "SKF", "Steel", "NOS", 10,
             "Main Warehouse", "RACK-A", "C-01", "T-02", 12],
        ])
        rows = read_rows(sheet)
        self.assertEqual(len(rows), 2)

        result = import_items(rows, user=self.admin, opening_document_number="OPN-IMP-1",
                              opening_warehouse=self.warehouse)
        self.assertEqual(result["created"], 2)
        self.assertEqual(result["opening_lines"], 2)
        self.assertEqual(result["errors"], [])
        self.assertTrue(Item.objects.filter(item_number="IMP-001").exists())

        doc = OpeningStockDocument.objects.get(document_number="OPN-IMP-1")
        self.assertEqual(doc.status, "DRAFT")   # a draft until a human posts it

        from stock import services
        services.post_document(doc, user=self.admin)
        self.assertEqual(StockBalance.total_for_item(
            Item.objects.get(item_number="IMP-001")), D("30.000"))

    def test_existing_items_are_skipped_unless_update_is_requested(self):
        Item.objects.create(item_number="IMP-003", name="ORIGINAL NAME",
                            category=ItemCategory.objects.first(),
                            uom=UnitOfMeasure.objects.get(code="NOS"))
        sheet = self._sheet([["IMP-003", "NEW NAME", "Pump Spares", "", "", "NOS", 0,
                              "", "", "", "", ""]])
        result = import_items(read_rows(sheet), user=self.admin, update_existing=False)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(Item.objects.get(item_number="IMP-003").name, "ORIGINAL NAME")

        sheet.seek(0)
        result = import_items(read_rows(sheet), user=self.admin, update_existing=True)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(Item.objects.get(item_number="IMP-003").name, "NEW NAME")

    def test_price_columns_in_the_sheet_are_ignored(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["Item Number", "Item Name", "Category", "UOM", "Rate", "Amount", "GST"])
        ws.append(["IMP-004", "SHOULD IGNORE MONEY", "Pump Spares", "NOS", 250, 5000, 18])
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        buf.name = "items.xlsx"

        rows = read_rows(buf)
        self.assertEqual(len(rows), 1)
        self.assertNotIn("rate", rows[0])
        self.assertNotIn("amount", rows[0])
        import_items(rows, user=self.admin)
        item = Item.objects.get(item_number="IMP-004")
        self.assertEqual(item.name, "SHOULD IGNORE MONEY")

    def test_bad_rows_are_reported_without_stopping_the_import(self):
        sheet = self._sheet([
            ["IMP-005", "GOOD ROW", "Pump Spares", "", "", "NOS", 0, "", "", "", "", ""],
            ["", "NO ITEM NUMBER", "Pump Spares", "", "", "NOS", 0, "", "", "", "", ""],
        ])
        result = import_items(read_rows(sheet), user=self.admin)
        self.assertEqual(result["created"], 1)
