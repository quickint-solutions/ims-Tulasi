from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from accounts.models import Role
from accounts.permissions_catalog import DEFAULT_ROLES
from django.contrib.auth import get_user_model
from items.models import Item
from masters.models import (ItemCategory, Location, Rack, RackColumn, RackTable,
                            UnitOfMeasure, Warehouse)
from . import services
from .models import (AdjustmentDocument, AdjustmentItem, DocumentStatus, InwardDocument,
                     InwardItem, MovementType, OpeningStockDocument, OpeningStockItem,
                     OutwardDocument, OutwardItem, StockBalance, StockMovement,
                     TransferDocument, TransferItem)

User = get_user_model()
D = Decimal


class StockEngineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("seed_defaults", verbosity=0)
        cls.user = User.objects.create_user(
            "tester", password="pw12345678",
            role=Role.objects.get(code="SUPER_ADMIN"), is_superuser=True)
        cls.uom = UnitOfMeasure.objects.get(code="NOS")
        cls.category = ItemCategory.objects.first()
        cls.wh_main = Warehouse.objects.create(code="MAIN", name="Main Warehouse")
        cls.wh_serv = Warehouse.objects.create(code="SERV", name="Service Warehouse")

        def build_location(wh, rack_code, col_code, tab_code):
            rack = Rack.objects.create(warehouse=wh, code=rack_code)
            col = RackColumn.objects.create(rack=rack, code=col_code)
            tab = RackTable.objects.create(column=col, code=tab_code)
            return Location.objects.create(warehouse=wh, rack=rack, column=col, table=tab)

        cls.loc_a = build_location(cls.wh_main, "RACK-A", "C-01", "T-01")
        cls.loc_b = build_location(cls.wh_main, "RACK-B", "C-02", "T-03")
        cls.loc_s = build_location(cls.wh_serv, "RACK-A", "C-01", "T-02")

        cls.item = Item.objects.create(
            item_number="SP-001", name="BOILER FEED PUMP IMPELLER",
            category=cls.category, uom=cls.uom, reorder_level=D("4"),
            minimum_stock=D("2"), maximum_stock=D("20"))

    # -- helpers ----------------------------------------------------------
    def _inward(self, number, location, qty):
        doc = InwardDocument.objects.create(
            document_number=number, warehouse=location.warehouse,
            document_date=timezone.localdate(), created_by=self.user)
        InwardItem.objects.create(document=doc, item=self.item, location=location,
                                  quantity=D(str(qty)))
        return services.post_document(doc, user=self.user)

    def _outward(self, number, location, qty, allow_negative=False):
        doc = OutwardDocument.objects.create(
            document_number=number, warehouse=location.warehouse,
            document_date=timezone.localdate(), allow_negative=allow_negative,
            created_by=self.user)
        OutwardItem.objects.create(document=doc, item=self.item, location=location,
                                   quantity=D(str(qty)))
        return services.post_document(doc, user=self.user)

    # -- tests ------------------------------------------------------------
    def test_location_code_is_built_from_the_hierarchy(self):
        self.assertEqual(self.loc_a.code, "MAIN/RACK-A/C-01/T-01")

    def test_opening_inward_outward_arithmetic(self):
        opening = OpeningStockDocument.objects.create(
            document_number="OPN-001", warehouse=self.wh_main, created_by=self.user)
        OpeningStockItem.objects.create(document=opening, item=self.item,
                                        location=self.loc_a, quantity=D("50"))
        services.post_document(opening, user=self.user)
        self._inward("IN-001", self.loc_a, 30)
        self._outward("OUT-001", self.loc_a, 20)

        # 50 + 30 - 20 = 60
        self.assertEqual(StockBalance.total_for_item(self.item), D("60.000"))
        self.assertEqual(
            StockBalance.objects.get(item=self.item, location=self.loc_a).quantity,
            D("60.000"))

    def test_balance_after_is_recorded_on_every_row(self):
        self._inward("IN-010", self.loc_a, 10)
        self._inward("IN-011", self.loc_a, 5)
        self._outward("OUT-010", self.loc_a, 3)
        rows = list(StockMovement.objects.filter(item=self.item).order_by("id"))
        self.assertEqual([r.balance_after for r in rows],
                         [D("10.000"), D("15.000"), D("12.000")])

    def test_outward_beyond_available_stock_is_blocked(self):
        self._inward("IN-020", self.loc_a, 5)
        with self.assertRaises(services.InsufficientStockError):
            self._outward("OUT-020", self.loc_a, 6)
        # Nothing moved and the document stayed a draft.
        self.assertEqual(StockBalance.total_for_item(self.item), D("5.000"))

    def test_admin_override_allows_negative_stock(self):
        self._inward("IN-021", self.loc_a, 5)
        self._outward("OUT-021", self.loc_a, 8, allow_negative=True)
        self.assertEqual(StockBalance.total_for_item(self.item), D("-3.000"))

    def test_override_requires_the_permission(self):
        plain = User.objects.create_user(
            "storeuser", password="pw12345678",
            role=Role.objects.get(code="STORE_USER"))
        doc = OutwardDocument.objects.create(
            document_number="OUT-022", warehouse=self.wh_main, allow_negative=True,
            created_by=plain)
        OutwardItem.objects.create(document=doc, item=self.item, location=self.loc_a,
                                   quantity=D("1"))
        with self.assertRaises(services.StockError):
            services.post_document(doc, user=plain)

    def test_transfer_moves_between_warehouses_without_changing_the_total(self):
        self._inward("IN-030", self.loc_a, 40)
        doc = TransferDocument.objects.create(
            document_number="TRF-001", from_warehouse=self.wh_main,
            to_warehouse=self.wh_serv, created_by=self.user)
        TransferItem.objects.create(document=doc, item=self.item,
                                    from_location=self.loc_a, to_location=self.loc_s,
                                    quantity=D("15"))
        services.post_document(doc, user=self.user)

        self.assertEqual(StockBalance.total_for_item(self.item), D("40.000"))
        self.assertEqual(StockBalance.total_for_item(self.item, self.wh_main), D("25.000"))
        self.assertEqual(StockBalance.total_for_item(self.item, self.wh_serv), D("15.000"))

    def test_same_item_in_many_locations_sums_correctly(self):
        self._inward("IN-040", self.loc_a, 20)
        self._inward("IN-041", self.loc_b, 10)
        doc = TransferDocument.objects.create(
            document_number="TRF-002", from_warehouse=self.wh_main,
            to_warehouse=self.wh_serv, created_by=self.user)
        TransferItem.objects.create(document=doc, item=self.item, from_location=self.loc_a,
                                    to_location=self.loc_s, quantity=D("5"))
        services.post_document(doc, user=self.user)
        self.assertEqual(StockBalance.total_for_item(self.item), D("30.000"))
        self.assertEqual(StockBalance.objects.filter(item=self.item, quantity__gt=0).count(), 3)

    def test_adjustment_posts_the_difference_only(self):
        self._inward("IN-050", self.loc_a, 50)
        doc = AdjustmentDocument.objects.create(
            document_number="ADJ-001", warehouse=self.wh_main, created_by=self.user)
        AdjustmentItem.objects.create(document=doc, item=self.item, location=self.loc_a,
                                      physical_quantity=D("48"), reason="Count difference")
        services.post_document(doc, user=self.user)

        self.assertEqual(StockBalance.total_for_item(self.item), D("48.000"))
        row = StockMovement.objects.filter(movement_type=MovementType.ADJUSTMENT).get()
        self.assertEqual(row.quantity, D("2.000"))
        self.assertEqual(row.direction, -1)
        self.assertEqual(doc.lines.first().system_quantity, D("50.000"))

    def test_adjustment_upwards(self):
        self._inward("IN-051", self.loc_a, 50)
        doc = AdjustmentDocument.objects.create(
            document_number="ADJ-002", warehouse=self.wh_main, created_by=self.user)
        AdjustmentItem.objects.create(document=doc, item=self.item, location=self.loc_a,
                                      physical_quantity=D("52"))
        services.post_document(doc, user=self.user)
        self.assertEqual(StockBalance.total_for_item(self.item), D("52.000"))

    def test_reversal_keeps_the_original_rows_and_restores_the_balance(self):
        self._inward("IN-060", self.loc_a, 100)
        doc = self._outward("OUT-060", self.loc_a, 40)
        self.assertEqual(StockBalance.total_for_item(self.item), D("60.000"))

        services.cancel_document(doc, user=self.user, reason="Wrong department")
        doc.refresh_from_db()
        self.assertEqual(doc.status, DocumentStatus.CANCELLED)
        self.assertEqual(StockBalance.total_for_item(self.item), D("100.000"))
        # The original outward row is still there, plus a correction row.
        self.assertEqual(
            StockMovement.objects.filter(document_number="OUT-060").count(), 2)
        self.assertTrue(
            StockMovement.objects.filter(document_number="OUT-060", is_reversal=True).exists())

    def test_movements_cannot_be_deleted(self):
        self._inward("IN-070", self.loc_a, 5)
        row = StockMovement.objects.first()
        with self.assertRaises(RuntimeError):
            row.delete()

    def test_a_document_cannot_be_posted_twice(self):
        doc = self._inward("IN-080", self.loc_a, 5)
        with self.assertRaises(services.DocumentStateError):
            services.post_document(doc, user=self.user)
        self.assertEqual(StockBalance.total_for_item(self.item), D("5.000"))

    def test_recalculate_balances_repairs_a_tampered_row(self):
        self._inward("IN-090", self.loc_a, 25)
        StockBalance.objects.filter(item=self.item).update(quantity=D("999"))
        changed = services.recalculate_balances(item=self.item)
        self.assertEqual(changed, 1)
        self.assertEqual(StockBalance.total_for_item(self.item), D("25.000"))

    def test_stock_status_thresholds(self):
        self.assertEqual(self.item.stock_status, "OUT_OF_STOCK")
        self._inward("IN-100", self.loc_a, 3)
        self.assertEqual(self.item.stock_status, "LOW_STOCK")
        self._inward("IN-101", self.loc_a, 10)
        self.assertEqual(self.item.stock_status, "IN_STOCK")
        self._inward("IN-102", self.loc_a, 20)
        self.assertEqual(self.item.stock_status, "OVERSTOCK")

    def test_duplicate_document_number_is_rejected(self):
        from django.db import IntegrityError, transaction
        self._inward("IN-110", self.loc_a, 5)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InwardDocument.objects.create(
                    document_number="IN-110", warehouse=self.wh_main, created_by=self.user)

    def test_manual_document_numbers_are_free_form(self):
        for number in ("IN-001", "GRN-125", "2026-458", "MANUAL-001"):
            doc = InwardDocument.objects.create(
                document_number=number, warehouse=self.wh_main, created_by=self.user)
            InwardItem.objects.create(document=doc, item=self.item, location=self.loc_a,
                                      quantity=D("1"))
            services.post_document(doc, user=self.user)
        self.assertEqual(StockBalance.total_for_item(self.item), D("4.000"))
