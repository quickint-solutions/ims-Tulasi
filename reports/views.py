from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone

from accounts import audit
from accounts.models import AuditLog, User
from core.excel import excel_response
from core.mixins import querystring_without_page
from core.utils import parse_date
from items.models import Item
from masters.models import ItemCategory, Location, Rack, RackColumn, RackTable, Warehouse
from stock.models import MovementType
from .definitions import REPORT_GROUPS, REPORTS


def _collect_filters(request):
    g = request.GET
    return {
        "q": g.get("q", "").strip(),
        "item": g.get("item") or None,
        "category": g.get("category") or None,
        "warehouse": g.get("warehouse") or None,
        "rack": g.get("rack") or None,
        "column": g.get("column") or None,
        "table": g.get("table") or None,
        "location": g.get("location") or None,
        "type": g.get("type") or None,
        "user": g.get("user") or None,
        "document": g.get("document", "").strip(),
        "date_from": parse_date(g.get("date_from")),
        "date_to": parse_date(g.get("date_to")),
    }


def _filter_summary(f):
    bits = []
    if f["date_from"] or f["date_to"]:
        bits.append(f"{f['date_from'] or 'start'} to {f['date_to'] or 'today'}")
    for key, model, label in (("warehouse", Warehouse, "Warehouse"),
                              ("category", ItemCategory, "Category"),
                              ("location", Location, "Location"),
                              ("item", Item, "Item")):
        if f.get(key):
            obj = model.objects.filter(pk=f[key]).first()
            if obj:
                bits.append(f"{label}: {obj}")
    if f.get("type"):
        bits.append(f"Type: {f['type']}")
    if f.get("q"):
        bits.append(f'Search: "{f["q"]}"')
    return " · ".join(bits) or "No filters applied"


def index(request):
    if not request.user.has_perm_code("report.view"):
        raise PermissionDenied
    grouped = {g: [] for g in REPORT_GROUPS}
    for spec in REPORTS.values():
        grouped.setdefault(spec["group"], []).append(spec)
    for group in grouped.values():
        group.sort(key=lambda s: s["title"])
    return render(request, "reports/index.html", {
        "grouped": grouped,
        "page_title": "Reports",
        "page_subtitle": f"{len(REPORTS)} reports. Every one is quantity-based and "
                         f"exports to Excel.",
        "nav": "reports",
    })


def run(request, slug):
    if not request.user.has_perm_code("report.view"):
        raise PermissionDenied
    spec = REPORTS.get(slug)
    if spec is None:
        raise Http404("Unknown report.")
    filters = _collect_filters(request)
    result = spec["build"](filters)
    rows = result["rows"]

    if request.GET.get("export") == "excel":
        if not request.user.has_perm_code("report.export"):
            raise PermissionDenied
        return _export(spec, result, filters, request)

    paginator = Paginator(rows, 100)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "reports/run.html", {
        "spec": spec, "result": result, "rows": page_obj.object_list,
        "page_obj": page_obj, "is_paginated": paginator.num_pages > 1,
        "paginator": paginator, "querystring": querystring_without_page(request),
        "row_count": len(rows),
        "filter_summary": _filter_summary(filters),
        "page_title": spec["title"], "page_subtitle": spec["description"],
        "nav": "reports",
        "warehouses": request.user.warehouse_queryset(),
        "categories": ItemCategory.objects.filter(is_active=True).select_related("parent"),
        "racks": Rack.objects.filter(is_active=True).select_related("warehouse"),
        "columns_list": RackColumn.objects.filter(is_active=True).select_related("rack"),
        "tables_list": RackTable.objects.filter(is_active=True).select_related("column"),
        "locations": Location.objects.filter(is_active=True)[:500],
        "users": User.objects.filter(is_active=True).order_by("username"),
        "movement_types": MovementType.choices,
        "filters": filters,
    })


def _export(spec, result, filters, request):
    numeric = result.get("numeric", set())
    date_cols = result.get("date_cols", set())
    columns = []
    for i, head in enumerate(result["columns"]):
        kind = "num" if i in numeric else ("date" if i in date_cols else "text")
        columns.append((head, i, kind))
    stamp = timezone.localtime().strftime("%d-%m-%Y %H:%M")
    audit.log(AuditLog.Action.EXPORT, object_type="Report", object_label=spec["title"],
              description=f"Exported {spec['title']} ({len(result['rows'])} rows)")
    return excel_response([{
        "name": spec["title"][:31],
        "title": spec["title"],
        "subtitle": f"{_filter_summary(filters)} · generated {stamp} · quantities only",
        "columns": columns,
        "rows": result["rows"],
        "totals": result.get("totals"),
    }], f"{spec['slug']}_{timezone.localdate():%Y%m%d}.xlsx")


def export_all_monthly(request):
    """One workbook with the monthly pack: inward, outward, movement, current stock."""
    if not request.user.has_perm_code("report.export"):
        raise PermissionDenied
    filters = _collect_filters(request)
    sheets = []
    for slug in ("monthly_inward", "monthly_outward", "monthly_movement", "current_stock"):
        spec = REPORTS[slug]
        result = spec["build"](filters)
        numeric = result.get("numeric", set())
        date_cols = result.get("date_cols", set())
        sheets.append({
            "name": spec["title"][:31], "title": spec["title"],
            "subtitle": _filter_summary(filters) + " · quantities only",
            "columns": [(h, i, "num" if i in numeric else
                         ("date" if i in date_cols else "text"))
                        for i, h in enumerate(result["columns"])],
            "rows": result["rows"], "totals": result.get("totals"),
        })
    audit.log(AuditLog.Action.EXPORT, object_type="Report",
              description="Exported the monthly report pack")
    return excel_response(sheets, f"monthly_pack_{timezone.localdate():%Y%m%d}.xlsx")


def export_all_yearly(request):
    if not request.user.has_perm_code("report.export"):
        raise PermissionDenied
    filters = _collect_filters(request)
    sheets = []
    for slug in ("yearly_inward", "yearly_outward", "yearly_movement", "current_stock"):
        spec = REPORTS[slug]
        result = spec["build"](filters)
        numeric = result.get("numeric", set())
        date_cols = result.get("date_cols", set())
        sheets.append({
            "name": spec["title"][:31], "title": spec["title"],
            "subtitle": _filter_summary(filters) + " · quantities only",
            "columns": [(h, i, "num" if i in numeric else
                         ("date" if i in date_cols else "text"))
                        for i, h in enumerate(result["columns"])],
            "rows": result["rows"], "totals": result.get("totals"),
        })
    audit.log(AuditLog.Action.EXPORT, object_type="Report",
              description="Exported the yearly report pack")
    return excel_response(sheets, f"yearly_pack_{timezone.localdate():%Y%m%d}.xlsx")
