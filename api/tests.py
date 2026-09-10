import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role
from items.models import Item
from masters.models import Location
from stock.models import StockBalance
from .models import ApiKey

User = get_user_model()
D = Decimal


class ApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_defaults", verbosity=0)
        call_command("seed_demo", verbosity=0)
        cls.admin = User.objects.filter(is_superuser=True).first()
        cls.item = Item.objects.get(item_number="SP-001")
        cls.location = Location.objects.filter(warehouse__code="MAIN").first()
        cls.read_key, cls.read_raw = ApiKey.issue(
            name="reader", user=cls.admin, scopes=["read"])
        cls.write_key, cls.write_raw = ApiKey.issue(
            name="writer", user=cls.admin, scopes=["read", "write"])

    def read_headers(self):
        return {"HTTP_AUTHORIZATION": f"ApiKey {self.read_raw}"}

    def write_headers(self):
        return {"HTTP_AUTHORIZATION": f"ApiKey {self.write_raw}"}

    # -- authentication ---------------------------------------------------
    def test_unauthenticated_request_is_rejected(self):
        response = self.client.get("/api/v1/items/")
        self.assertIn(response.status_code, (401, 403))

    def test_invalid_key_is_rejected(self):
        response = self.client.get("/api/v1/items/",
                                   HTTP_AUTHORIZATION="ApiKey sk_not_a_real_key")
        self.assertEqual(response.status_code, 401)

    def test_revoked_key_is_rejected(self):
        ApiKey.objects.filter(pk=self.read_key.pk).update(is_active=False)
        response = self.client.get("/api/v1/items/", **self.read_headers())
        self.assertEqual(response.status_code, 401)
        ApiKey.objects.filter(pk=self.read_key.pk).update(is_active=True)

    def test_x_api_key_header_also_works(self):
        response = self.client.get("/api/v1/items/", HTTP_X_API_KEY=self.read_raw)
        self.assertEqual(response.status_code, 200)

    def test_only_a_hash_is_stored(self):
        self.assertNotIn(self.read_raw, ApiKey.objects.values_list("key_hash", flat=True))
        self.assertEqual(self.read_key.key_hash, ApiKey.hash_key(self.read_raw))

    # -- read endpoints ---------------------------------------------------
    def test_api_root_lists_the_endpoints(self):
        response = self.client.get("/api/v1/", **self.read_headers())
        self.assertEqual(response.status_code, 200)
        for key in ("items", "warehouses", "inward", "outward", "by_barcode", "by_qr"):
            self.assertIn(key, response.json())

    def test_item_list_and_detail(self):
        response = self.client.get("/api/v1/items/", **self.read_headers())
        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.json()["count"], 0)

        detail = self.client.get(f"/api/v1/items/{self.item.pk}/", **self.read_headers())
        self.assertEqual(detail.status_code, 200)
        body = detail.json()
        self.assertEqual(body["item_number"], "SP-001")
        self.assertIn("stock_by_location", body)

    def test_no_response_field_is_monetary(self):
        response = self.client.get(f"/api/v1/items/{self.item.pk}/", **self.read_headers())
        text = json.dumps(response.json()).lower()
        for word in ("price", '"rate"', "amount", "gst", "currency", "valuation"):
            self.assertNotIn(word, text, f"'{word}' leaked into the item API response")

    def test_barcode_lookup(self):
        response = self.client.get(f"/api/v1/barcode/{self.item.barcode_number}/",
                                   **self.read_headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["item_number"], "SP-001")

    def test_barcode_lookup_reports_an_unknown_code_clearly(self):
        response = self.client.get("/api/v1/barcode/NOT-A-CODE/", **self.read_headers())
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "not_found")

    def test_qr_token_lookup(self):
        response = self.client.get(f"/api/v1/qr/{self.item.qr_token}/", **self.read_headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["item_number"], "SP-001")

    def test_item_stock_endpoint(self):
        response = self.client.get(f"/api/v1/items/{self.item.pk}/stock/",
                                   **self.read_headers())
        self.assertEqual(response.status_code, 200)
        self.assertIn("total_quantity", response.json())

    def test_movement_ledger_is_read_only(self):
        response = self.client.post("/api/v1/movements/", {}, **self.write_headers())
        self.assertEqual(response.status_code, 405)

    # -- write endpoints --------------------------------------------------
    def test_read_only_key_cannot_post_inward(self):
        payload = {"document_number": "API-IN-001", "warehouse": "MAIN",
                   "lines": [{"item": "SP-001", "location": self.location.code,
                              "quantity": "5"}]}
        response = self.client.post("/api/v1/stock/inward/", payload,
                                    content_type="application/json", **self.read_headers())
        self.assertEqual(response.status_code, 403)

    def test_inward_via_api_moves_stock(self):
        before = StockBalance.total_for_item(self.item)
        payload = {"document_number": "API-IN-002", "warehouse": "MAIN",
                   "supplier": "Test Supplier",
                   "lines": [{"item": "SP-001", "location": self.location.code,
                              "quantity": "7"}]}
        response = self.client.post("/api/v1/stock/inward/", payload,
                                    content_type="application/json", **self.write_headers())
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["status"], "POSTED")
        self.assertEqual(StockBalance.total_for_item(self.item), before + D("7"))

    def test_outward_beyond_stock_returns_409(self):
        payload = {"document_number": "API-OUT-001", "warehouse": "MAIN",
                   "lines": [{"item": "SP-001", "location": self.location.code,
                              "quantity": "999999"}]}
        response = self.client.post("/api/v1/stock/outward/", payload,
                                    content_type="application/json", **self.write_headers())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "insufficient_stock")

    def test_duplicate_document_number_is_rejected(self):
        payload = {"document_number": "API-IN-003", "warehouse": "MAIN",
                   "lines": [{"item": "SP-001", "location": self.location.code,
                              "quantity": "1"}]}
        first = self.client.post("/api/v1/stock/inward/", payload,
                                 content_type="application/json", **self.write_headers())
        self.assertEqual(first.status_code, 201)
        second = self.client.post("/api/v1/stock/inward/", payload,
                                  content_type="application/json", **self.write_headers())
        self.assertEqual(second.status_code, 400)
        self.assertIn("document_number", second.json())

    def test_unknown_item_is_reported(self):
        payload = {"document_number": "API-IN-004", "warehouse": "MAIN",
                   "lines": [{"item": "NOPE-999", "location": self.location.code,
                              "quantity": "1"}]}
        response = self.client.post("/api/v1/stock/inward/", payload,
                                    content_type="application/json", **self.write_headers())
        self.assertEqual(response.status_code, 400)

    def test_draft_mode_leaves_stock_untouched(self):
        before = StockBalance.total_for_item(self.item)
        payload = {"document_number": "API-IN-005", "warehouse": "MAIN", "post": False,
                   "lines": [{"item": "SP-001", "location": self.location.code,
                              "quantity": "9"}]}
        response = self.client.post("/api/v1/stock/inward/", payload,
                                    content_type="application/json", **self.write_headers())
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "DRAFT")
        self.assertEqual(StockBalance.total_for_item(self.item), before)

    def test_transfer_via_api(self):
        src = self.location
        dst = Location.objects.filter(warehouse__code="SERV").first()
        # make sure there is something to move
        self.client.post("/api/v1/stock/inward/",
                         {"document_number": "API-IN-006", "warehouse": "MAIN",
                          "lines": [{"item": "SP-001", "location": src.code,
                                     "quantity": "20"}]},
                         content_type="application/json", **self.write_headers())
        total_before = StockBalance.total_for_item(self.item)
        response = self.client.post(
            "/api/v1/stock/transfer/",
            {"document_number": "API-TRF-001", "from_warehouse": "MAIN",
             "to_warehouse": "SERV",
             "lines": [{"item": "SP-001", "from_location": src.code,
                        "to_location": dst.code, "quantity": "6"}]},
            content_type="application/json", **self.write_headers())
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(StockBalance.total_for_item(self.item), total_before)
        self.assertEqual(
            StockBalance.objects.get(item=self.item, location=dst).quantity, D("6.000"))

    def test_api_calls_are_logged(self):
        from .models import ApiLog
        ApiLog.objects.all().delete()
        self.client.get("/api/v1/items/", **self.read_headers())
        log = ApiLog.objects.first()
        self.assertIsNotNone(log)
        self.assertEqual(log.path, "/api/v1/items/")
        self.assertEqual(log.status_code, 200)

    def test_item_delete_deactivates_instead_of_removing(self):
        response = self.client.delete(f"/api/v1/items/{self.item.pk}/",
                                      **self.write_headers())
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertFalse(self.item.is_active)
        self.item.is_active = True
        self.item.save()
