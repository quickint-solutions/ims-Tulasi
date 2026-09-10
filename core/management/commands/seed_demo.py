"""Create a small but realistic demo dataset for evaluating the system."""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Role
from items.models import Item
from masters.models import (ItemCategory, Location, Rack, RackColumn, RackTable,
                            UnitOfMeasure, Warehouse)
from stock import services
from stock.models import (InwardDocument, InwardItem, OpeningStockDocument,
                          OpeningStockItem, OutwardDocument, OutwardItem)

User = get_user_model()

ITEMS = [
    ("SP-001", "BOILER FEED PUMP IMPELLER", "Pump Spares", "KSB", "SS 316", 12.5, "250", "Silver", 2, 20, 4),
    ("SP-002", "MECHANICAL SEAL 45MM", "Pump Spares", "Burgmann", "SIC/Carbon", 1.2, "45", "Black", 4, 30, 8),
    ("SP-003", "DEEP GROOVE BALL BEARING 6205", "Bearings", "SKF", "Chrome Steel", 0.13, "25x52x15", "Steel", 10, 200, 25),
    ("SP-004", "TAPER ROLLER BEARING 30206", "Bearings", "FAG", "Chrome Steel", 0.22, "30x62x17", "Steel", 8, 120, 16),
    ("VALVE-015", "GATE VALVE 4 INCH FLANGED", "Valve Spares", "Audco", "CI", 28.0, "100", "Grey", 1, 12, 3),
    ("VALVE-021", "BALL VALVE 1 INCH SS", "Valve Spares", "Leader", "SS 304", 1.8, "25", "Silver", 3, 40, 6),
    ("BOILER-FD-001", "FD FAN BEARING HOUSING", "Boiler Spares", "Thermax", "CI", 34.0, "300", "Grey", 1, 6, 2),
    ("BOILER-FD-002", "BOILER SIGHT GLASS 200MM", "Boiler Spares", "Thermax", "Borosilicate", 0.6, "200", "Clear", 4, 40, 8),
    ("GASK-101", "SPIRAL WOUND GASKET 4 INCH", "Gaskets", "Champion", "SS 316 / Graphite", 0.25, "100", "Grey", 20, 300, 40),
    ("GASK-102", "CAF GASKET SHEET 1.5MM", "Gaskets", "Klinger", "CAF", 4.0, "1000x1000", "Red", 2, 20, 4),
    ("FAST-201", "HEX BOLT M12 X 60 SS", "Fasteners", "Unbrako", "SS 304", 0.08, "M12x60", "Silver", 100, 2000, 250),
    ("FAST-202", "SPRING WASHER M12", "Fasteners", "Unbrako", "Spring Steel", 0.01, "M12", "Black", 200, 4000, 500),
    ("ELEC-301", "CONTACTOR 32A 3 POLE", "Electrical Spares", "Siemens", "Polycarbonate", 0.9, "32A", "Grey", 2, 20, 5),
    ("ELEC-302", "MCB 32A DP C CURVE", "Electrical Spares", "L&T", "Polycarbonate", 0.2, "32A", "White", 5, 60, 12),
    ("INST-401", "PRESSURE GAUGE 0-16 BAR", "Instrumentation", "Wika", "SS 304", 0.7, "100", "Silver", 3, 25, 6),
    ("INST-402", "RTD PT100 SENSOR 6MM", "Instrumentation", "Tempsens", "SS 316", 0.3, "6x150", "Silver", 4, 30, 8),
    ("RUB-501", "NITRILE O-RING 50MM", "Rubber Items", "Parker", "NBR", 0.02, "50", "Black", 25, 500, 60),
    ("RUB-502", "RUBBER EXPANSION BELLOW 4 INCH", "Rubber Items", "Resistoflex", "EPDM", 3.2, "100", "Black", 2, 15, 4),
    ("PIPE-601", "SEAMLESS PIPE 2 INCH SCH 40", "Pipes", "Jindal", "MS", 22.0, "50", "Black", 5, 60, 10),
    ("TOOL-701", "TORQUE WRENCH 40-200 NM", "Tools", "Taparia", "Chrome Vanadium", 2.4, "1/2 inch", "Blue", 1, 6, 2),
]

WAREHOUSES = [
    ("MAIN", "Main Warehouse", "Ahmedabad"),
    ("SERV", "Service Warehouse", "Ahmedabad"),
    ("SITE", "Site Warehouse", "Vadodara"),
]


class Command(BaseCommand):
    help = "Create demo warehouses, locations, items and posted stock movements."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Delete existing demo items first.")

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(20260902)
        admin = User.objects.filter(is_superuser=True).first()
        if admin is None:
            admin = User.objects.create_superuser(
                "admin", "admin@example.com", "ChangeMe123!",
                role=Role.objects.filter(code="SUPER_ADMIN").first())
            self.stdout.write(self.style.WARNING(
                "Created superuser 'admin' with password 'ChangeMe123!' - change it."))

        nos = UnitOfMeasure.objects.get(code="NOS")

        # Warehouses + rack grid
        locations = {}
        for code, name, city in WAREHOUSES:
            wh, _ = Warehouse.objects.get_or_create(
                code=code, defaults={"name": name, "city": city})
            for rack_code in ("RACK-A", "RACK-B"):
                rack, _ = Rack.objects.get_or_create(warehouse=wh, code=rack_code)
                for ci in range(1, 4):
                    col, _ = RackColumn.objects.get_or_create(rack=rack, code=f"C-{ci:02d}")
                    for ti in range(1, 4):
                        tab, _ = RackTable.objects.get_or_create(column=col, code=f"T-{ti:02d}")
                        loc, _ = Location.objects.get_or_create(
                            warehouse=wh, rack=rack, column=col, table=tab,
                            defaults={"code": f"{wh.code}/{rack_code}/{col.code}/{tab.code}"})
                        locations.setdefault(wh.code, []).append(loc)
        self.stdout.write(f"Warehouses: {Warehouse.objects.count()}, "
                          f"locations: {Location.objects.count()}.")

        # Items
        made = 0
        for (number, name, category, make, material, weight, size, colour,
             minimum, maximum, reorder) in ITEMS:
            cat = ItemCategory.objects.filter(name=category).first() \
                or ItemCategory.objects.create(name=category)
            item, created = Item.objects.get_or_create(
                item_number=number,
                defaults={
                    "name": name, "category": cat, "manufacturer": make,
                    "material": material, "weight": Decimal(str(weight)), "weight_unit": "KG",
                    "size": size, "size_unit": "MM", "colour": colour, "uom": nos,
                    "minimum_stock": minimum, "maximum_stock": maximum,
                    "reorder_level": reorder, "barcode_number": number,
                    "spare_type": Item.SpareType.MECHANICAL,
                    "application": "Plant maintenance spare",
                    "created_by": admin, "updated_by": admin,
                })
            made += int(created)
        self.stdout.write(f"Items: {Item.objects.count()} ({made} new).")

        if OpeningStockDocument.objects.exists():
            self.stdout.write("Stock documents already exist - skipping movement demo.")
            return

        items = list(Item.objects.all())
        main_locs = locations["MAIN"]

        # Opening stock
        opening = OpeningStockDocument.objects.create(
            document_number="OPN-001", warehouse=Warehouse.objects.get(code="MAIN"),
            document_date=timezone.localdate() - timedelta(days=180),
            remarks="Demo opening balances", created_by=admin)
        for item in items:
            OpeningStockItem.objects.create(
                document=opening, item=item, location=random.choice(main_locs),
                quantity=Decimal(random.randint(10, 120)))
        services.post_document(opening, user=admin)

        # A run of inward and outward documents over the last six months
        today = timezone.localdate()
        for n in range(1, 19):
            day = today - timedelta(days=random.randint(1, 175))
            doc = InwardDocument.objects.create(
                document_number=f"GRN-{100 + n}", warehouse=Warehouse.objects.get(code="MAIN"),
                document_date=day, supplier=random.choice(
                    ["Shakti Traders", "Gujarat Bearings", "Nova Engineering",
                     "Precision Spares Co"]),
                reference_number=f"PO-{2000 + n}", created_by=admin)
            for item in random.sample(items, random.randint(2, 5)):
                InwardItem.objects.create(document=doc, item=item,
                                          location=random.choice(main_locs),
                                          quantity=Decimal(random.randint(5, 60)))
            services.post_document(doc, user=admin)

        from stock.models import StockBalance
        for n in range(1, 25):
            day = today - timedelta(days=random.randint(0, 170))
            doc = OutwardDocument.objects.create(
                document_number=f"ISSUE-{200 + n}",
                warehouse=Warehouse.objects.get(code="MAIN"), document_date=day,
                destination=random.choice(
                    ["Maintenance Dept", "Boiler Section", "Utility Section",
                     "Project Site", "Workshop"]),
                created_by=admin)
            picked = 0
            for balance in StockBalance.objects.filter(
                    warehouse__code="MAIN", quantity__gt=5).order_by("?")[:4]:
                qty = Decimal(random.randint(1, min(15, int(balance.quantity))))
                OutwardItem.objects.create(document=doc, item=balance.item,
                                           location=balance.location, quantity=qty)
                picked += 1
            if picked == 0:
                doc.delete()
                continue
            try:
                services.post_document(doc, user=admin)
            except services.StockError:
                doc.delete()

        self.stdout.write(self.style.SUCCESS(
            f"Demo data ready: {Item.objects.count()} items, "
            f"{StockBalance.objects.filter(quantity__gt=0).count()} stocked bins."))
