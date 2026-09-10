"""Seed the roles, permissions, units, label template and starter categories.

Idempotent: safe to run on every deploy.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import AppPermission, Role
from accounts.permissions_catalog import DEFAULT_ROLES, PERMISSION_GROUPS
from core.models import CompanySettings, SystemSettings
from integration.models import ErpNextSettings
from labels.models import LabelTemplate, PrinterSetting
from masters.models import ItemCategory, UnitOfMeasure

UNITS = [
    ("NOS", "Numbers", 0), ("SET", "Set", 0), ("PAIR", "Pair", 0), ("PC", "Piece", 0),
    ("KG", "Kilogram", 3), ("GM", "Gram", 3), ("MT", "Metric Tonne", 3),
    ("MTR", "Metre", 3), ("MM", "Millimetre", 2), ("FT", "Feet", 2),
    ("LTR", "Litre", 3), ("ML", "Millilitre", 2),
    ("BOX", "Box", 0), ("ROLL", "Roll", 0), ("SHEET", "Sheet", 0), ("BAG", "Bag", 0),
]

CATEGORIES = [
    "Boiler Spares", "Pump Spares", "Valve Spares", "Mechanical Spares",
    "Electrical Spares", "Instrumentation", "Bearings", "Fasteners",
    "Fabrication Items", "Rubber Items", "Gaskets", "Pipes", "Fittings",
    "Consumables", "Tools", "Other",
]


class Command(BaseCommand):
    help = "Seed permissions, roles, units of measure, categories and the default label."

    @transaction.atomic
    def handle(self, *args, **options):
        # Permissions
        created = 0
        for group, perms in PERMISSION_GROUPS:
            for code, label in perms:
                _obj, made = AppPermission.objects.update_or_create(
                    code=code, defaults={"label": label, "group": group})
                created += int(made)
        self.stdout.write(f"Permissions: {AppPermission.objects.count()} total, {created} new.")

        # Roles
        for code, spec in DEFAULT_ROLES.items():
            role, _ = Role.objects.update_or_create(
                code=code, defaults={"name": spec["name"],
                                     "description": spec["description"],
                                     "is_system": True})
            role.permissions.set(AppPermission.objects.filter(code__in=spec["permissions"]))
        self.stdout.write(f"Roles: {Role.objects.count()}.")

        # Units
        for code, name, dp in UNITS:
            UnitOfMeasure.objects.get_or_create(
                code=code, defaults={"name": name, "decimal_places": dp})
        self.stdout.write(f"Units of measure: {UnitOfMeasure.objects.count()}.")

        # Categories
        for name in CATEGORIES:
            ItemCategory.objects.get_or_create(
                name=name, parent=None,
                defaults={"code": name.upper().replace(" ", "_")[:32]})
        self.stdout.write(f"Categories: {ItemCategory.objects.count()}.")

        # Label template - the 50 x 25 mm industrial label
        LabelTemplate.objects.get_or_create(
            name="Standard 50 x 25 mm",
            defaults={"width_mm": 50, "height_mm": 25, "is_default": True,
                      "scan_hint_text": "SCAN TO VIEW PRODUCT DETAILS"})

        # A browser-print profile that works with any OS printer, Seznik Mini included
        PrinterSetting.objects.get_or_create(
            name="Default label printer (browser)",
            defaults={"printer_type": PrinterSetting.PrinterType.THERMAL_LABEL,
                      "connection_type": PrinterSetting.ConnectionType.BROWSER,
                      "label_width_mm": 50, "label_height_mm": 25, "label_gap_mm": 2,
                      "dpi": 203, "is_default": True,
                      "notes": "Set paper size 50 x 25 mm and margins to none in the "
                               "browser print dialog."})

        company = CompanySettings.load()
        self._seed_logo(company)
        SystemSettings.load()
        ErpNextSettings.load()
        self.stdout.write(self.style.SUCCESS("Defaults seeded."))

    def _seed_logo(self, company):
        """Install the bundled brand logo on a fresh system.

        Only ever runs when no logo has been set, so it never overwrites one an
        administrator uploaded at Settings -> Company.
        """
        from pathlib import Path

        from django.conf import settings as django_settings
        from django.core.files.base import ContentFile

        if company.logo:
            return
        source = Path(django_settings.BASE_DIR) / "static" / "img" / "logo.png"
        if not source.exists():
            return
        company.logo.save("logo.png", ContentFile(source.read_bytes()), save=False)
        if company.company_name in ("", "Spares Inventory"):
            company.company_name = "Tulsi"
            company.short_name = "TULSI"
        company.save()
        self.stdout.write("Company logo installed from static/img/logo.png.")
