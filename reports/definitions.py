"""The 20 reports from section 25.

Every report is quantity-only. There is no price, value or amount column
anywhere in this module, by design.
"""
from decimal import Decimal

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncMonth, TruncYear

from items.models import Item
from masters.models import ItemCategory, Location, Warehouse
from stock.models import MovementType, StockBalance, StockMovement

ZERO = Decimal("0")

REPORTS = {}


def report(slug, title, description, group, filters):
    def wrap(fn):
        REPORTS[slug] = {"slug": slug, "title": title, "description": description,
                         "group": group, "filters": filters, "build": fn}
        return fn
    return wrap


COMMON_STOCK_FILTERS = ["q", "warehouse", "category", "rack", "column", "table", "location"]
COMMON_MOVE_FILTERS = ["date_from", "date_to", "q", "item", "category", "warehouse",
                       "location", "type", "user", "document"]


def _apply_balance_filters(qs, f):
    if f.get("warehouse"):
        qs = qs.filter(warehouse_id=f["warehouse"])
    if f.get("location"):
        qs = qs.filter(location_id=f["location"])
    if f.get("rack"):
        qs = qs.filter(location__rack_id=f["rack"])
    if f.get("column"):
        qs = qs.filter(location__column_id=f["column"])
    if f.get("table"):
        qs = qs.filter(location__table_id=f["table"])
    if f.get("category"):
        qs = qs.filter(Q(item__category_id=f["category"])
                       | Q(item__sub_category_id=f["category"]))
    if f.get("item"):
        qs = qs.filter(item_id=f["item"])
    if f.get("q"):
        q = f["q"]
        qs = qs.filter(Q(item__item_number__icontains=q) | Q(item__name__icontains=q)
                       | Q(item__barcode_number__icontains=q))
    return qs


def _apply_movement_filters(qs, f):
    qs = _apply_balance_filters(qs, f)
    if f.get("type"):
        qs = qs.filter(movement_type=f["type"])
    if f.get("user"):
        qs = qs.filter(user_id=f["user"])
    if f.get("document"):
        qs = qs.filter(document_number__icontains=f["document"])
    return qs.between(f.get("date_from"), f.get("date_to"))


def _movements(f, direction=None, types=None):
    qs = StockMovement.objects.select_related("item__uom", "warehouse", "location", "user")
    if direction is not None:
        qs = qs.filter(direction=direction)
    if types:
        qs = qs.filter(movement_type__in=types)
    return _apply_movement_filters(qs, f)


# ---------------------------------------------------------------- 1-5 stock
@report("current_stock", "Current Stock Report",
        "Quantity on hand for every item, summed across all locations.",
        "Stock", COMMON_STOCK_FILTERS)
def r_current_stock(f):
    qs = _apply_balance_filters(StockBalance.objects.all(), f)
    rows = (qs.values("item__item_number", "item__name", "item__uom__code",
                      "item__category__name", "item__minimum_stock",
                      "item__reorder_level", "item__maximum_stock")
            .annotate(qty=Sum("quantity"), bins=Count("location", distinct=True))
            .order_by("item__item_number"))
    data = []
    for r in rows:
        qty = r["qty"] or ZERO
        reorder = r["item__reorder_level"] or ZERO
        maximum = r["item__maximum_stock"] or ZERO
        if qty <= 0:
            status = "Out of stock"
        elif reorder and qty <= reorder:
            status = "Low stock"
        elif maximum and qty > maximum:
            status = "Overstock"
        else:
            status = "In stock"
        data.append([r["item__item_number"], r["item__name"], r["item__category__name"] or "",
                     r["item__uom__code"], qty, r["item__minimum_stock"], reorder, maximum,
                     r["bins"], status])
    return {
        "columns": ["Item Number", "Item Name", "Category", "UOM", "Quantity",
                    "Min", "Reorder", "Max", "Locations", "Status"],
        "numeric": {4, 5, 6, 7, 8},
        "rows": data,
        "totals": ["Total", "", "", "", sum((r[4] for r in data), ZERO), "", "", "", "", ""],
    }


@report("warehouse_stock", "Warehouse Stock Report",
        "Quantity held in each warehouse, by item.", "Stock", COMMON_STOCK_FILTERS)
def r_warehouse_stock(f):
    qs = _apply_balance_filters(StockBalance.objects.all(), f)
    rows = (qs.values("warehouse__name", "item__item_number", "item__name",
                      "item__uom__code")
            .annotate(qty=Sum("quantity")).filter(qty__gt=0)
            .order_by("warehouse__name", "item__item_number"))
    data = [[r["warehouse__name"], r["item__item_number"], r["item__name"],
             r["item__uom__code"], r["qty"]] for r in rows]
    return {"columns": ["Warehouse", "Item Number", "Item Name", "UOM", "Quantity"],
            "numeric": {4}, "rows": data,
            "totals": ["Total", "", "", "", sum((r[4] for r in data), ZERO)]}


@report("location_stock", "Location-wise Stock Report",
        "Quantity in every rack / column / table bin.", "Stock", COMMON_STOCK_FILTERS)
def r_location_stock(f):
    qs = _apply_balance_filters(
        StockBalance.objects.select_related("location__rack", "location__column",
                                            "location__table"), f).filter(quantity__gt=0)
    data = [[b.warehouse.name, b.location.rack_code, b.location.column_code,
             b.location.table_code, b.location.code, b.item.item_number, b.item.name,
             b.item.uom.code, b.quantity]
            for b in qs.select_related("item__uom", "warehouse").order_by(
                "warehouse__name", "location__code", "item__item_number")]
    return {"columns": ["Warehouse", "Rack", "Column", "Table", "Location Code",
                        "Item Number", "Item Name", "UOM", "Quantity"],
            "numeric": {8}, "rows": data,
            "totals": ["Total", "", "", "", "", "", "", "",
                       sum((r[8] for r in data), ZERO)]}


@report("category_stock", "Category-wise Stock Report",
        "Total quantity and item count per category.", "Stock", COMMON_STOCK_FILTERS)
def r_category_stock(f):
    qs = _apply_balance_filters(StockBalance.objects.all(), f)
    rows = (qs.values("item__category__name")
            .annotate(qty=Sum("quantity"), items=Count("item", distinct=True))
            .order_by("-qty"))
    data = [[r["item__category__name"] or "Uncategorised", r["items"], r["qty"] or ZERO]
            for r in rows]
    return {"columns": ["Category", "Items", "Quantity"], "numeric": {1, 2}, "rows": data,
            "totals": ["Total", sum(r[1] for r in data), sum((r[2] for r in data), ZERO)]}


@report("item_stock", "Item-wise Stock Report",
        "One row per item and bin, showing where every unit sits.",
        "Stock", COMMON_STOCK_FILTERS)
def r_item_stock(f):
    qs = _apply_balance_filters(
        StockBalance.objects.select_related("item__uom", "warehouse", "location"), f)
    data = [[b.item.item_number, b.item.name, b.warehouse.name, b.location.code,
             b.item.uom.code, b.quantity, b.reserved_quantity, b.available_quantity]
            for b in qs.filter(quantity__gt=0).order_by("item__item_number",
                                                        "warehouse__name")]
    return {"columns": ["Item Number", "Item Name", "Warehouse", "Location", "UOM",
                        "Quantity", "Reserved", "Available"],
            "numeric": {5, 6, 7}, "rows": data,
            "totals": ["Total", "", "", "", "", sum((r[5] for r in data), ZERO),
                       sum((r[6] for r in data), ZERO), sum((r[7] for r in data), ZERO)]}


# ------------------------------------------------------------- 6-9 documents
def _movement_rows(qs):
    return [[m.movement_date, m.get_movement_type_display(), m.document_number,
             m.item.item_number, m.item.name, m.item.uom.code, m.quantity,
             m.warehouse.name, m.location.rack_code, m.location.column_code,
             m.location.table_code, m.party, m.reference,
             m.user.username if m.user_id else "", m.remarks]
            for m in qs]


MOVEMENT_COLUMNS = ["Date", "Type", "Document No", "Item Number", "Item Name", "UOM",
                    "Quantity", "Warehouse", "Rack", "Column", "Table",
                    "Party / Destination", "Reference", "User", "Remarks"]


@report("inward", "Inward Report", "Every receipt line in the period.",
        "Transactions", COMMON_MOVE_FILTERS)
def r_inward(f):
    qs = _movements(f, types=[MovementType.INWARD]).order_by("-movement_date", "-id")
    rows = _movement_rows(qs)
    return {"columns": MOVEMENT_COLUMNS, "numeric": {6}, "date_cols": {0}, "rows": rows,
            "totals": ["Total", "", "", "", "", "", sum((r[6] for r in rows), ZERO)]}


@report("outward", "Outward Report", "Every issue line in the period.",
        "Transactions", COMMON_MOVE_FILTERS)
def r_outward(f):
    qs = _movements(f, types=[MovementType.OUTWARD]).order_by("-movement_date", "-id")
    rows = _movement_rows(qs)
    return {"columns": MOVEMENT_COLUMNS, "numeric": {6}, "date_cols": {0}, "rows": rows,
            "totals": ["Total", "", "", "", "", "", sum((r[6] for r in rows), ZERO)]}


@report("transfer", "Stock Transfer Report", "Movements between warehouses and bins.",
        "Transactions", COMMON_MOVE_FILTERS)
def r_transfer(f):
    qs = _movements(f, types=[MovementType.TRANSFER_IN, MovementType.TRANSFER_OUT]
                    ).order_by("-movement_date", "-id")
    rows = _movement_rows(qs)
    return {"columns": MOVEMENT_COLUMNS, "numeric": {6}, "date_cols": {0}, "rows": rows}


@report("adjustment", "Stock Adjustment Report",
        "Physical verification differences, with reasons.",
        "Transactions", COMMON_MOVE_FILTERS)
def r_adjustment(f):
    qs = _movements(f, types=[MovementType.ADJUSTMENT]).order_by("-movement_date", "-id")
    rows = [[m.movement_date, m.document_number, m.item.item_number, m.item.name,
             m.item.uom.code, m.signed_quantity, m.warehouse.name, m.location.code,
             m.party, m.user.username if m.user_id else "", m.remarks] for m in qs]
    return {"columns": ["Date", "Document No", "Item Number", "Item Name", "UOM",
                        "Difference", "Warehouse", "Location", "Reason", "User", "Remarks"],
            "numeric": {5}, "date_cols": {0}, "rows": rows,
            "totals": ["Total", "", "", "", "", sum((r[5] for r in rows), ZERO)]}


@report("movement_ledger", "Stock Movement Ledger",
        "The complete audit trail: every row ever posted.",
        "Transactions", COMMON_MOVE_FILTERS)
def r_ledger(f):
    qs = _movements(f).order_by("-movement_date", "-created_at", "-id")
    rows = [[m.movement_date, m.created_at.strftime("%H:%M"),
             m.get_movement_type_display(), m.document_number, m.item.item_number,
             m.item.name, m.item.uom.code, m.signed_quantity, m.balance_after,
             m.warehouse.name, m.location.code, m.party,
             m.user.username if m.user_id else "", m.remarks]
            for m in qs]
    return {"columns": ["Date", "Time", "Movement Type", "Document No", "Item Number",
                        "Item Name", "UOM", "Quantity", "Balance After", "Warehouse",
                        "Location", "Party", "User", "Remarks"],
            "numeric": {7, 8}, "date_cols": {0}, "rows": rows}


# --------------------------------------------------------------- 11-13 alerts
@report("low_stock", "Low Stock Report", "Items at or below their reorder level.",
        "Alerts", ["q", "category", "warehouse"])
def r_low_stock(f):
    qs = Item.objects.filter(is_active=True).annotate(qty=Sum("stock_balances__quantity"))
    if f.get("category"):
        qs = qs.filter(Q(category_id=f["category"]) | Q(sub_category_id=f["category"]))
    if f.get("q"):
        qs = qs.filter(Q(item_number__icontains=f["q"]) | Q(name__icontains=f["q"]))
    qs = qs.filter(qty__gt=0, reorder_level__gt=0, qty__lte=F("reorder_level"))
    rows = [[i.item_number, i.name, i.category.name if i.category_id else "", i.uom.code,
             i.qty or ZERO, i.reorder_level, i.minimum_stock,
             (i.reorder_level or ZERO) - (i.qty or ZERO)]
            for i in qs.select_related("uom", "category").order_by("item_number")]
    return {"columns": ["Item Number", "Item Name", "Category", "UOM", "Quantity",
                        "Reorder Level", "Minimum Stock", "Shortfall"],
            "numeric": {4, 5, 6, 7}, "rows": rows}


@report("out_of_stock", "Out of Stock Report", "Items with zero quantity everywhere.",
        "Alerts", ["q", "category"])
def r_out_of_stock(f):
    qs = Item.objects.filter(is_active=True).annotate(qty=Sum("stock_balances__quantity"))
    if f.get("category"):
        qs = qs.filter(Q(category_id=f["category"]) | Q(sub_category_id=f["category"]))
    if f.get("q"):
        qs = qs.filter(Q(item_number__icontains=f["q"]) | Q(name__icontains=f["q"]))
    qs = qs.filter(Q(qty__lte=0) | Q(qty__isnull=True))
    rows = [[i.item_number, i.name, i.category.name if i.category_id else "", i.uom.code,
             i.reorder_level, i.minimum_stock,
             i.movements.order_by("-movement_date").values_list(
                 "movement_date", flat=True).first() or ""]
            for i in qs.select_related("uom", "category").order_by("item_number")]
    return {"columns": ["Item Number", "Item Name", "Category", "UOM", "Reorder Level",
                        "Minimum Stock", "Last Movement"],
            "numeric": {4, 5}, "date_cols": {6}, "rows": rows}


@report("item_movement", "Item Movement Report",
        "Inward, outward and net movement per item for the period.",
        "Movement", COMMON_MOVE_FILTERS)
def r_item_movement(f):
    qs = _apply_movement_filters(StockMovement.objects.all(), f)
    rows = (qs.values("item__item_number", "item__name", "item__uom__code")
            .annotate(
                inward=Sum("quantity", filter=Q(direction=1)),
                outward=Sum("quantity", filter=Q(direction=-1)),
                moves=Count("id"))
            .order_by("item__item_number"))
    data = []
    for r in rows:
        i, o = r["inward"] or ZERO, r["outward"] or ZERO
        data.append([r["item__item_number"], r["item__name"], r["item__uom__code"],
                     i, o, i - o, r["moves"]])
    return {"columns": ["Item Number", "Item Name", "UOM", "Inward Qty", "Outward Qty",
                        "Net Change", "Movements"],
            "numeric": {3, 4, 5, 6}, "rows": data,
            "totals": ["Total", "", "", sum((r[3] for r in data), ZERO),
                       sum((r[4] for r in data), ZERO), sum((r[5] for r in data), ZERO),
                       sum(r[6] for r in data)]}


# ------------------------------------------------------ 14-19 period reports
def _period_report(f, trunc, label_fmt, types, direction=None):
    qs = _apply_movement_filters(StockMovement.objects.all(), f)
    if types:
        qs = qs.filter(movement_type__in=types)
    if direction is not None:
        qs = qs.filter(direction=direction)
    rows = (qs.annotate(period=trunc("movement_date"))
            .values("period", "item__item_number", "item__name", "item__uom__code")
            .annotate(qty=Sum("quantity"))
            .order_by("period", "item__item_number"))
    data = [[r["period"].strftime(label_fmt), r["item__item_number"], r["item__name"],
             r["item__uom__code"], r["qty"] or ZERO] for r in rows]
    return data


@report("monthly_inward", "Monthly Item-wise Inward",
        "Receipts per item per month.", "Periodic", COMMON_MOVE_FILTERS)
def r_monthly_inward(f):
    data = _period_report(f, TruncMonth, "%b %Y", [MovementType.INWARD,
                                                   MovementType.OPENING])
    return {"columns": ["Month", "Item Number", "Item Name", "UOM", "Inward Quantity"],
            "numeric": {4}, "rows": data,
            "totals": ["Total", "", "", "", sum((r[4] for r in data), ZERO)]}


@report("monthly_outward", "Monthly Item-wise Outward",
        "Issues per item per month.", "Periodic", COMMON_MOVE_FILTERS)
def r_monthly_outward(f):
    data = _period_report(f, TruncMonth, "%b %Y", [MovementType.OUTWARD])
    return {"columns": ["Month", "Item Number", "Item Name", "UOM", "Outward Quantity"],
            "numeric": {4}, "rows": data,
            "totals": ["Total", "", "", "", sum((r[4] for r in data), ZERO)]}


@report("yearly_inward", "Yearly Item-wise Inward", "Receipts per item per year.",
        "Periodic", COMMON_MOVE_FILTERS)
def r_yearly_inward(f):
    data = _period_report(f, TruncYear, "%Y", [MovementType.INWARD, MovementType.OPENING])
    return {"columns": ["Year", "Item Number", "Item Name", "UOM", "Inward Quantity"],
            "numeric": {4}, "rows": data,
            "totals": ["Total", "", "", "", sum((r[4] for r in data), ZERO)]}


@report("yearly_outward", "Yearly Item-wise Outward", "Issues per item per year.",
        "Periodic", COMMON_MOVE_FILTERS)
def r_yearly_outward(f):
    data = _period_report(f, TruncYear, "%Y", [MovementType.OUTWARD])
    return {"columns": ["Year", "Item Number", "Item Name", "UOM", "Outward Quantity"],
            "numeric": {4}, "rows": data,
            "totals": ["Total", "", "", "", sum((r[4] for r in data), ZERO)]}


def _period_movement(f, trunc, label_fmt):
    qs = _apply_movement_filters(StockMovement.objects.all(), f)
    rows = (qs.annotate(period=trunc("movement_date"))
            .values("period", "item__item_number", "item__name", "item__uom__code")
            .annotate(inward=Sum("quantity", filter=Q(direction=1)),
                      outward=Sum("quantity", filter=Q(direction=-1)))
            .order_by("period", "item__item_number"))
    data = []
    for r in rows:
        i, o = r["inward"] or ZERO, r["outward"] or ZERO
        data.append([r["period"].strftime(label_fmt), r["item__item_number"],
                     r["item__name"], r["item__uom__code"], i, o, i - o])
    return data


@report("monthly_movement", "Monthly Item Movement",
        "Inward, outward and net per item per month.", "Periodic", COMMON_MOVE_FILTERS)
def r_monthly_movement(f):
    data = _period_movement(f, TruncMonth, "%b %Y")
    return {"columns": ["Month", "Item Number", "Item Name", "UOM", "Inward", "Outward",
                        "Net"],
            "numeric": {4, 5, 6}, "rows": data,
            "totals": ["Total", "", "", "", sum((r[4] for r in data), ZERO),
                       sum((r[5] for r in data), ZERO), sum((r[6] for r in data), ZERO)]}


@report("yearly_movement", "Yearly Item Movement",
        "Inward, outward and net per item per year.", "Periodic", COMMON_MOVE_FILTERS)
def r_yearly_movement(f):
    data = _period_movement(f, TruncYear, "%Y")
    return {"columns": ["Year", "Item Number", "Item Name", "UOM", "Inward", "Outward",
                        "Net"],
            "numeric": {4, 5, 6}, "rows": data,
            "totals": ["Total", "", "", "", sum((r[4] for r in data), ZERO),
                       sum((r[5] for r in data), ZERO), sum((r[6] for r in data), ZERO)]}


@report("warehouse_movement", "Warehouse Movement Report",
        "Inward and outward totals per warehouse.", "Movement", COMMON_MOVE_FILTERS)
def r_warehouse_movement(f):
    qs = _apply_movement_filters(StockMovement.objects.all(), f)
    rows = (qs.values("warehouse__name")
            .annotate(inward=Sum("quantity", filter=Q(direction=1)),
                      outward=Sum("quantity", filter=Q(direction=-1)),
                      moves=Count("id"), items=Count("item", distinct=True))
            .order_by("warehouse__name"))
    data = []
    for r in rows:
        i, o = r["inward"] or ZERO, r["outward"] or ZERO
        data.append([r["warehouse__name"], r["items"], r["moves"], i, o, i - o])
    return {"columns": ["Warehouse", "Items", "Movements", "Inward", "Outward", "Net"],
            "numeric": {1, 2, 3, 4, 5}, "rows": data,
            "totals": ["Total", sum(r[1] for r in data), sum(r[2] for r in data),
                       sum((r[3] for r in data), ZERO), sum((r[4] for r in data), ZERO),
                       sum((r[5] for r in data), ZERO)]}


REPORT_GROUPS = ["Stock", "Transactions", "Movement", "Periodic", "Alerts"]
