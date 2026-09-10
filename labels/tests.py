import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from items.models import Item
from masters.models import Location
from stock.models import StockBalance
from .generators import barcode_svg, qr_svg
from .models import LabelPrintLog, LabelTemplate, PrinterSetting
from .render import label_context

User = get_user_model()
D = Decimal


def _render_svg_barcode(svg, px_per_mm=12):
    """Rasterise a barcode SVG the way a browser would, for decoding."""
    import re

    from PIL import Image, ImageDraw

    box = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    width, height = float(box.group(1)), float(box.group(2))
    img = Image.new("L", (round(width * px_per_mm), round(height * px_per_mm)), 255)
    draw = ImageDraw.Draw(img)
    for x, y, w, h in re.findall(
            r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"', svg):
        x, y, w, h = (float(v) * px_per_mm for v in (x, y, w, h))
        draw.rectangle([x, y, x + w, y + h], fill=0)
    return img


class BarcodeGeometryTests(TestCase):
    """The bars must fit the canvas.

    python-barcode positions bars in millimetres inside an SVG whose viewBox is
    unitless. If the two are not reconciled the symbol is laid out 3.78x too wide
    and silently truncated - it still *looks* like a barcode, but no scanner can
    read it. These tests fail if that ever comes back.
    """

    CODES = ["SP-001", "BOILER-FD-001", "VALVE-015", "GASK-101", "2026-458",
             "MANUAL-001", "A1/B2", "PUMP-001"]

    def test_every_bar_falls_inside_the_canvas(self):
        import re
        for code in self.CODES:
            with self.subTest(code=code):
                svg = barcode_svg(code)
                width = float(re.search(r'viewBox="0 0 ([\d.]+) ', svg).group(1))
                bars = [(float(x), float(w)) for x, w in re.findall(
                    r'<rect x="([\d.]+)" y="[\d.]+" width="([\d.]+)"', svg)]
                self.assertGreater(len(bars), 20, "symbol looks too short to be complete")
                self.assertLessEqual(max(x + w for x, w in bars), width,
                                     f"{code}: the barcode is truncated")
                self.assertGreaterEqual(min(x for x, _ in bars), 0)

    def test_no_millimetre_units_leak_into_the_viewbox_coordinate_space(self):
        self.assertNotIn('mm"', barcode_svg("SP-001").split(">", 1)[1])

    def test_rendered_barcode_decodes_back_to_the_item_number(self):
        try:
            from pyzbar.pyzbar import decode
        except (ImportError, OSError):
            self.skipTest("pyzbar/libzbar not installed - geometry tests still cover this")
        for code in self.CODES:
            for module_width, module_height in ((0.22, 9.0), (0.3, 12.0)):
                with self.subTest(code=code, module_width=module_width):
                    img = _render_svg_barcode(barcode_svg(
                        code, module_width=module_width, module_height=module_height))
                    results = decode(img)
                    self.assertTrue(results, f"{code}: nothing decoded")
                    self.assertEqual(results[0].data.decode(), code)
                    self.assertEqual(results[0].type, "CODE128")

    def test_rendered_qr_decodes_back_to_the_url(self):
        try:
            from pyzbar.pyzbar import decode
        except (ImportError, OSError):
            self.skipTest("pyzbar/libzbar not installed")
        import re

        from PIL import Image, ImageDraw

        url = "http://192.168.1.45:8000/i/wEfJeXsOISZbO635g5iOqQ/"
        svg = qr_svg(url)
        size = float(re.search(r'viewBox="0 0 ([\d.]+) ', svg).group(1))
        scale, quiet = 10, 4
        img = Image.new("L", (round((size + quiet * 2) * scale),) * 2, 255)
        draw = ImageDraw.Draw(img)
        for m in re.finditer(r"M(\d+),(\d+)H(\d+)V(\d+)H\d+z", svg):
            x0, y0, x1, y1 = (int(v) for v in m.groups())
            draw.rectangle([(x0 + quiet) * scale, (y0 + quiet) * scale,
                            (x1 + quiet) * scale - 1, (y1 + quiet) * scale - 1], fill=0)
        results = decode(img)
        self.assertTrue(results, "QR did not decode")
        self.assertEqual(results[0].data.decode(), url)


class BarcodeGenerationTests(TestCase):
    def test_code128_barcode_is_scalable_svg(self):
        svg = barcode_svg("SP-001")
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("viewBox", svg)
        self.assertNotIn('width="', svg.split(">", 1)[0])

    def test_barcode_encodes_different_codes_differently(self):
        self.assertNotEqual(barcode_svg("SP-001"), barcode_svg("SP-002"))

    def test_qr_is_svg_with_a_viewbox(self):
        svg = qr_svg("https://example.com/i/abc123")
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("viewBox", svg)

    def test_long_item_numbers_still_encode(self):
        svg = barcode_svg("BOILER-FD-ASSEMBLY-001-REV-C")
        self.assertTrue(svg.startswith("<svg"))


class LabelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_defaults", verbosity=0)
        call_command("seed_demo", verbosity=0)
        cls.admin = User.objects.filter(is_superuser=True).first()
        cls.item = Item.objects.get(item_number="SP-001")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_default_template_is_50_by_25_mm(self):
        template = LabelTemplate.get_default()
        self.assertEqual(float(template.width_mm), 50.0)
        self.assertEqual(float(template.height_mm), 25.0)
        self.assertEqual(template.scan_hint_text, "SCAN TO VIEW PRODUCT DETAILS")

    def test_label_context_carries_all_three_areas(self):
        ctx = label_context(self.item)
        self.assertTrue(ctx["qr_svg"].startswith("<svg"))       # area 1
        self.assertTrue(ctx["barcode_svg"].startswith("<svg"))  # area 2
        self.assertEqual(ctx["item"].name, self.item.name)      # area 3
        self.assertTrue(ctx["show_scan_hint"])

    def test_preview_page_renders_the_label_at_true_size(self):
        response = self.client.get(reverse("labels:preview"),
                                   {"item": self.item.pk, "copies": 1, "zoom": "3"})
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("SCAN TO VIEW PRODUCT DETAILS", body)
        self.assertIn(self.item.name, body)
        self.assertIn(self.item.barcode_number, body)
        self.assertIn("50 mm", body)

    def test_label_css_pins_the_physical_size(self):
        with open("static/css/label.css") as fh:
            css = fh.read()
        self.assertIn("--lw:50mm", css)
        self.assertIn("--lh:25mm", css)
        # The label must not reserve space for a logo.
        self.assertNotIn("label__logo", css)

    def test_print_sheet_records_history(self):
        LabelPrintLog.objects.all().delete()
        response = self.client.get(reverse("labels:print"),
                                   {"item": self.item.pk, "copies": 3})
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertEqual(body.count('class="label '), 3)
        log = LabelPrintLog.objects.get(item=self.item)
        self.assertEqual(log.copies, 3)
        self.assertEqual(log.barcode_snapshot, self.item.barcode_number)

    def test_reprint_is_flagged(self):
        self.client.get(reverse("labels:print"), {"item": self.item.pk, "copies": 1})
        self.client.get(reverse("labels:print"), {"item": self.item.pk, "copies": 1})
        self.assertTrue(LabelPrintLog.objects.filter(item=self.item, is_reprint=True).exists())

    def test_batch_print_by_category(self):
        response = self.client.post(reverse("labels:print_batch"), {
            "mode": "category", "category": self.item.category_id, "copies": 1})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/barcode/print/", response["Location"])

    def test_test_print_works_without_arguments(self):
        printer = PrinterSetting.get_default()
        response = self.client.get(reverse("labels:test_print", args=[printer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("Test print", response.content.decode())


class PublicQrPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_defaults", verbosity=0)
        call_command("seed_demo", verbosity=0)
        cls.item = Item.objects.get(item_number="SP-001")

    def test_qr_url_uses_an_opaque_token_not_the_id(self):
        path = self.item.public_url_path
        self.assertIn(self.item.qr_token, path)
        self.assertNotIn(f"/{self.item.pk}/", path)
        self.assertGreaterEqual(len(self.item.qr_token), 16)

    def test_public_page_opens_without_logging_in(self):
        response = self.client.get(self.item.public_url_path)
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn(self.item.name, body)
        self.assertIn(self.item.item_number, body)

    def test_public_page_hides_internal_data(self):
        response = self.client.get(self.item.public_url_path)
        body = response.content.decode().lower()
        for leak in ("supplier", "grn-", "issue-", "admin", "api key", "created by"):
            self.assertNotIn(leak, body, f"'{leak}' leaked onto the public QR page")

    def test_public_page_shows_product_details_only_by_default(self):
        """The QR link is public, so stock and location must not be on it."""
        from core.models import SystemSettings
        row = SystemSettings.load()
        self.assertFalse(row.show_public_stock)
        self.assertFalse(row.show_public_location)

        response = self.client.get(self.item.public_url_path)
        body = response.content.decode()
        # Product details are present...
        self.assertIn(self.item.name, body)
        self.assertIn(self.item.manufacturer, body)
        self.assertIn(self.item.material, body)
        # ...internal figures are not.
        self.assertNotIn("Current stock", body)
        self.assertNotIn("Where it is stored", body)
        for balance in self.item.stock_balances.filter(quantity__gt=0):
            self.assertNotIn(balance.location.code, body)

    def test_stock_can_be_switched_back_on_for_a_closed_network(self):
        from core.models import SystemSettings
        row = SystemSettings.load()
        row.show_public_stock = True
        row.save()
        self.assertIn("Current stock", self.client.get(
            self.item.public_url_path).content.decode())
        row.show_public_stock = False
        row.save()

    def test_an_unknown_token_is_404(self):
        self.assertEqual(self.client.get("/i/definitelynotarealtoken/").status_code, 404)

    def test_public_page_can_be_switched_off(self):
        from core.models import SystemSettings
        row = SystemSettings.load()
        row.public_page_enabled = False
        row.save()
        self.assertEqual(self.client.get(self.item.public_url_path).status_code, 404)
        row.public_page_enabled = True
        row.save()

    def test_the_internal_scanner_still_shows_stock_and_location(self):
        """Hiding figures on the public page must not touch the staff workflow."""
        from django.contrib.auth import get_user_model
        admin = get_user_model().objects.filter(is_superuser=True).first()
        self.client.force_login(admin)
        from django.urls import reverse
        body = self.client.get(reverse("labels:scanner"),
                               {"code": self.item.barcode_number}).content.decode()
        self.assertIn("Available", body)
        self.assertIn("LOCATION", body.upper())


class ScannerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_defaults", verbosity=0)
        call_command("seed_demo", verbosity=0)
        cls.admin = User.objects.filter(is_superuser=True).first()
        cls.item = Item.objects.get(item_number="SP-001")
        cls.location = (StockBalance.objects.filter(item=cls.item, quantity__gt=0)
                        .first().location)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_scanning_a_known_barcode_shows_the_item_card(self):
        response = self.client.get(reverse("labels:scanner"),
                                   {"code": self.item.barcode_number})
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn(self.item.name, body)
        self.assertIn("Available", body)

    def test_scanning_an_unknown_barcode_says_so(self):
        response = self.client.get(reverse("labels:scanner"), {"code": "NOT-REGISTERED"},
                                   follow=True)
        self.assertContains(response, "Barcode not registered")

    def test_scanner_inward_posts_stock(self):
        before = StockBalance.total_for_item(self.item)
        response = self.client.post(
            reverse("labels:scanner_action", args=[self.item.pk, "inward"]),
            {"action": "INWARD", "item_id": self.item.pk, "document_number": "SCAN-IN-1",
             "location": self.location.pk, "quantity": "4", "party": "Walk-in",
             "remarks": ""})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(StockBalance.total_for_item(self.item), before + D("4"))

    def test_scanner_outward_respects_available_stock(self):
        before = StockBalance.total_for_item(self.item)
        response = self.client.post(
            reverse("labels:scanner_action", args=[self.item.pk, "outward"]),
            {"action": "OUTWARD", "item_id": self.item.pk, "document_number": "SCAN-OUT-1",
             "location": self.location.pk, "quantity": "999999", "party": "Maintenance"},
            follow=True)
        self.assertContains(response, "Insufficient stock")
        self.assertEqual(StockBalance.total_for_item(self.item), before)

    def test_barcode_lookup_json_endpoint(self):
        response = self.client.get(reverse("items:lookup"),
                                   {"code": self.item.barcode_number})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["found"])
