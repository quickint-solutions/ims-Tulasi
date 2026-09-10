"""Item master Excel/CSV import and export (section 51).

Quantity columns only. An optional Opening Quantity column posts opening stock
through the normal stock engine so the ledger stays the single source of truth.
"""
import csv
import io
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook

from masters.models import (ItemCategory, Location, Rack, RackColumn, RackTable,
                            UnitOfMeasure, Warehouse)
from stock.models import OpeningStockDocument, OpeningStockItem
from .models import Item

COLUMNS = [
    "Item Number", "Item Name", "Category", "Sub Category", "Description", "Make",
    "Model", "Material", "Material Grade", "Weight", "Weight Unit", "Size", "Size Unit",
    "Colour", "Type", "Application", "Specification", "Drawing Number", "OEM Part Number",
    "Alternate Part Number", "UOM", "Minimum Stock", "Maximum Stock", "Reorder Level",
    "Barcode", "Remarks", "Warehouse", "Rack", "Column", "Table", "Opening Quantity",
]

FIELD_MAP = {
    "item number": "item_number", "part number": "item_number", "item no": "item_number",
    "item name": "name", "name": "name",
    "category": "category", "sub category": "sub_category", "subcategory": "sub_category",
    "description": "description",
    "make": "manufacturer", "manufacturer": "manufacturer",
    "model": "model_number", "model number": "model_number",
    "material": "material", "material grade": "material_grade",
    "weight": "weight", "weight unit": "weight_unit",
    "size": "size", "size unit": "size_unit", "colour": "colour", "color": "colour",
    "type": "spare_type", "application": "application", "specification": "specification",
    "drawing number": "drawing_number",
    "oem part number": "oem_part_number", "alternate part number": "alternate_part_number",
    "uom": "uom", "unit": "uom", "unit of measurement": "uom",
    "minimum stock": "minimum_stock", "min stock": "minimum_stock",
    "maximum stock": "maximum_stock", "max stock": "maximum_stock",
    "reorder level": "reorder_level", "barcode": "barcode_number",
    "remarks": "remarks",
    "warehouse": "_warehouse", "rack": "_rack", "column": "_column", "table": "_table",
    "opening quantity": "_opening", "opening stock": "_opening",
}

NUMERIC = {"weight", "minimum_stock", "maximum_stock", "reorder_level"}


def _dec(value, default=None):
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return default


def read_rows(uploaded):
    """Yield dicts keyed by our internal field names."""
    name = (uploaded.name or "").lower()
    if name.endswith((".csv", ".txt")):
        text = uploaded.read().decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text))
        raw_rows = list(reader)
    else:
        wb = load_workbook(uploaded, read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        raw_rows = [[c for c in row] for row in ws.iter_rows(values_only=True)]
    if not raw_rows:
        return []
    header = [str(h or "").strip().lower() for h in raw_rows[0]]
    keys = [FIELD_MAP.get(h) for h in header]
    out = []
    for raw in raw_rows[1:]:
        if not any(str(c or "").strip() for c in raw):
            continue
        row = {}
        for key, value in zip(keys, raw):
            if key:
                row[key] = str(value).strip() if isinstance(value, str) else value
        if row.get("item_number"):
            out.append(row)
    return out


def _get_category(name, create):
    name = (str(name or "").strip() or "Uncategorised")
    cat = ItemCategory.objects.filter(name__iexact=name, parent__isnull=True).first()
    if cat is None and create:
        cat = ItemCategory.objects.create(name=name)
    return cat


def _get_subcategory(name, parent, create):
    name = str(name or "").strip()
    if not name or parent is None:
        return None
    sub = ItemCategory.objects.filter(name__iexact=name, parent=parent).first()
    if sub is None and create:
        sub = ItemCategory.objects.create(name=name, parent=parent,
                                          code=f"{parent.code}_{name}".upper()[:32])
    return sub


def _get_uom(code):
    code = (str(code or "").strip() or "NOS").upper()
    uom = UnitOfMeasure.objects.filter(code__iexact=code).first()
    if uom is None:
        uom = UnitOfMeasure.objects.create(code=code, name=code)
    return uom


def _get_location(row, fallback_warehouse, create):
    wh_name = str(row.get("_warehouse") or "").strip()
    warehouse = None
    if wh_name:
        warehouse = (Warehouse.objects.filter(name__iexact=wh_name).first()
                     or Warehouse.objects.filter(code__iexact=wh_name).first())
        if warehouse is None and create:
            warehouse = Warehouse.objects.create(
                code=wh_name.upper().replace(" ", "-")[:20], name=wh_name)
    warehouse = warehouse or fallback_warehouse
    if warehouse is None:
        return None

    rack = column = table = None
    r_code = str(row.get("_rack") or "").strip().upper()
    c_code = str(row.get("_column") or "").strip().upper()
    t_code = str(row.get("_table") or "").strip().upper()
    if r_code:
        rack = Rack.objects.filter(warehouse=warehouse, code__iexact=r_code).first()
        if rack is None and create:
            rack = Rack.objects.create(warehouse=warehouse, code=r_code)
    if c_code and rack:
        column = RackColumn.objects.filter(rack=rack, code__iexact=c_code).first()
        if column is None and create:
            column = RackColumn.objects.create(rack=rack, code=c_code)
    if t_code and column:
        table = RackTable.objects.filter(column=column, code__iexact=t_code).first()
        if table is None and create:
            table = RackTable.objects.create(column=column, code=t_code)

    location = Location.objects.filter(warehouse=warehouse, rack=rack, column=column,
                                       table=table).first()
    if location is None:
        if not create:
            return Location.objects.filter(warehouse=warehouse, is_default=True).first()
        parts = [warehouse.code] + [x.code for x in (rack, column, table) if x]
        location = Location.objects.create(warehouse=warehouse, rack=rack, column=column,
                                           table=table, code="/".join(parts))
    return location


@transaction.atomic
def import_items(rows, *, user, create_categories=True, create_locations=True,
                 update_existing=False, opening_document_number="", opening_warehouse=None):
    """Returns a summary dict. Raises nothing for bad rows - they are reported."""
    result = {"created": 0, "updated": 0, "skipped": 0, "opening_lines": 0, "errors": []}
    opening_doc = None
    if opening_document_number:
        opening_doc, _ = OpeningStockDocument.objects.get_or_create(
            document_number=opening_document_number.strip().upper(),
            defaults={"warehouse": opening_warehouse or Warehouse.objects.filter(
                is_active=True).first(),
                "document_date": timezone.localdate(),
                "remarks": "Created by item master import",
                "created_by": user})
        if opening_doc.status != "DRAFT":
            result["errors"].append(
                f"Opening document {opening_doc.document_number} is already posted; "
                f"opening quantities were skipped.")
            opening_doc = None

    for line_no, row in enumerate(rows, start=2):
        number = str(row.get("item_number") or "").strip().upper()
        if not number:
            continue
        try:
            existing = Item.objects.filter(item_number=number).first()
            if existing and not update_existing:
                result["skipped"] += 1
            else:
                category = _get_category(row.get("category"), create_categories)
                if category is None:
                    result["errors"].append(
                        f"Row {line_no}: category '{row.get('category')}' not found.")
                    result["skipped"] += 1
                    continue
                values = {
                    "name": str(row.get("name") or number)[:200],
                    "category": category,
                    "sub_category": _get_subcategory(row.get("sub_category"), category,
                                                     create_categories),
                    "uom": _get_uom(row.get("uom")),
                }
                for field in ("description", "manufacturer", "model_number", "material",
                              "material_grade", "weight_unit", "size", "size_unit", "colour",
                              "application", "specification", "drawing_number",
                              "oem_part_number", "alternate_part_number", "remarks"):
                    if row.get(field) not in (None, ""):
                        values[field] = str(row[field])[:255]
                for field in NUMERIC:
                    value = _dec(row.get(field))
                    if value is not None:
                        values[field] = value
                barcode = str(row.get("barcode_number") or "").strip().upper() or number
                values["barcode_number"] = barcode

                if existing:
                    for key, value in values.items():
                        setattr(existing, key, value)
                    existing.updated_by = user
                    existing.save()
                    item = existing
                    result["updated"] += 1
                else:
                    item = Item.objects.create(item_number=number, created_by=user,
                                               updated_by=user, **values)
                    result["created"] += 1

                location = _get_location(row, opening_warehouse, create_locations)
                if location and not item.default_location_id:
                    item.default_location = location
                    item.save(update_fields=["default_location"])

            qty = _dec(row.get("_opening"))
            if opening_doc and qty and qty > 0:
                item = Item.objects.get(item_number=number)
                location = _get_location(row, opening_doc.warehouse, create_locations)
                if location is None:
                    result["errors"].append(f"Row {line_no}: no location for opening stock.")
                else:
                    OpeningStockItem.objects.create(
                        document=opening_doc, item=item, location=location, quantity=qty,
                        remarks="Imported")
                    result["opening_lines"] += 1
        except Exception as exc:  # noqa: BLE001 - report and carry on
            result["errors"].append(f"Row {line_no} ({number}): {exc}")
            result["skipped"] += 1

    result["opening_document"] = opening_doc
    return result


def export_rows(queryset):
    """Item master rows for Excel export - quantities only."""
    rows = []
    for item in queryset.select_related("category", "sub_category", "uom",
                                        "default_location__warehouse"):
        loc = item.default_location
        rows.append([
            item.item_number, item.name,
            item.category.name if item.category_id else "",
            item.sub_category.name if item.sub_category_id else "",
            item.description, item.manufacturer, item.model_number, item.material,
            item.material_grade, item.weight, item.weight_unit, item.size, item.size_unit,
            item.colour, item.get_spare_type_display() if item.spare_type else "",
            item.application, item.specification, item.drawing_number, item.oem_part_number,
            item.alternate_part_number, item.uom.code,
            item.minimum_stock, item.maximum_stock, item.reorder_level,
            item.barcode_number, item.remarks,
            loc.warehouse.name if loc else "", loc.rack_code if loc else "",
            loc.column_code if loc else "", loc.table_code if loc else "",
            item.total_quantity,
        ])
    return rows
