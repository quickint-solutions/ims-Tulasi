from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.cache import cache
from django.db.models import Count, F, Q, Sum
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts import audit
from accounts.models import AuditLog
from items.models import Item
from masters.models import ItemCategory, Warehouse
from stock.models import (AdjustmentDocument, DocumentStatus, InwardDocument, MovementType,
                          OutwardDocument, StockBalance, StockMovement, TransferDocument)
from . import backup as backup_service
from .charts import SERIES_1, SERIES_2, grouped_bar_chart, horizontal_bar_chart
from .forms import BackupForm, CompanySettingsForm, RestoreForm, SystemSettingsForm
from .models import Backup, CompanySettings, SystemSettings
from .utils import last_n_months

ZERO = Decimal("0")


def dashboard(request):
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    today = timezone.localdate()

    balances = StockBalance.objects.all()
    total_qty = balances.aggregate(t=Sum("quantity"))["t"] or ZERO
    item_qs = Item.objects.filter(is_active=True).annotate(
        qty=Sum("stock_balances__quantity"))
    low_stock = item_qs.filter(qty__gt=0, reorder_level__gt=0,
                               qty__lte=F("reorder_level"))
    out_of_stock = item_qs.filter(Q(qty__lte=0) | Q(qty__isnull=True))

    today_moves = StockMovement.objects.filter(movement_date=today)
    inward_today = today_moves.filter(movement_type=MovementType.INWARD).aggregate(
        t=Sum("quantity"))["t"] or ZERO
    outward_today = today_moves.filter(movement_type=MovementType.OUTWARD).aggregate(
        t=Sum("quantity"))["t"] or ZERO

    months = last_n_months(12)
    month_keys = [m for m, _label in months]
    labels = [label for _m, label in months]
    start = month_keys[0]
    monthly = (StockMovement.objects.filter(movement_date__gte=start)
               .values("movement_date__year", "movement_date__month", "movement_type")
               .annotate(qty=Sum("quantity")))
    in_map, out_map = {}, {}
    for row in monthly:
        key = (row["movement_date__year"], row["movement_date__month"])
        if row["movement_type"] in (MovementType.INWARD, MovementType.OPENING):
            in_map[key] = in_map.get(key, ZERO) + (row["qty"] or ZERO)
        elif row["movement_type"] == MovementType.OUTWARD:
            out_map[key] = out_map.get(key, ZERO) + (row["qty"] or ZERO)
    inward_series = [in_map.get((m.year, m.month), ZERO) for m in month_keys]
    outward_series = [out_map.get((m.year, m.month), ZERO) for m in month_keys]

    category_rows = (balances.values("item__category__name")
                     .annotate(q=Sum("quantity")).order_by("-q")[:10])
    warehouse_rows = (balances.values("warehouse__name")
                      .annotate(q=Sum("quantity")).order_by("-q")[:10])
    top_moving = (StockMovement.objects.filter(movement_date__gte=start,
                                               movement_type=MovementType.OUTWARD)
                  .values("item__item_number", "item__name")
                  .annotate(q=Sum("quantity")).order_by("-q")[:10])

    context = {
        "page_title": "Dashboard",
        "page_subtitle": f"Quantity position as at {today:%d %b %Y}.",
        "nav": "dashboard",
        "total_items": Item.objects.filter(is_active=True).count(),
        "total_categories": ItemCategory.objects.filter(is_active=True).count(),
        "total_warehouses": Warehouse.objects.filter(is_active=True).count(),
        "total_locations": balances.values("location").distinct().count(),
        "total_quantity": total_qty,
        "inward_today": inward_today,
        "outward_today": outward_today,
        "low_stock_count": low_stock.count(),
        "out_of_stock_count": out_of_stock.count(),
        "low_stock_items": low_stock.select_related("uom")[:8],
        "recent_movements": (StockMovement.objects
                             .select_related("item__uom", "warehouse", "location", "user")[:12]),
        "recent_inward": InwardDocument.objects.filter(
            status=DocumentStatus.POSTED).select_related("warehouse")[:5],
        "recent_outward": OutwardDocument.objects.filter(
            status=DocumentStatus.POSTED).select_related("warehouse")[:5],
        "recent_transfers": TransferDocument.objects.filter(
            status=DocumentStatus.POSTED).select_related("from_warehouse",
                                                         "to_warehouse")[:5],
        "draft_count": (InwardDocument.objects.filter(status=DocumentStatus.DRAFT).count()
                        + OutwardDocument.objects.filter(status=DocumentStatus.DRAFT).count()
                        + TransferDocument.objects.filter(status=DocumentStatus.DRAFT).count()
                        + AdjustmentDocument.objects.filter(
                            status=DocumentStatus.DRAFT).count()),
        "chart_monthly": grouped_bar_chart(
            labels,
            [("Inward", SERIES_1, inward_series), ("Outward", SERIES_2, outward_series)],
            unit="units"),
        "chart_category": horizontal_bar_chart(
            [(r["item__category__name"] or "Uncategorised", r["q"]) for r in category_rows],
            unit="units"),
        "chart_warehouse": horizontal_bar_chart(
            [(r["warehouse__name"], r["q"]) for r in warehouse_rows], unit="units"),
        "chart_top_moving": horizontal_bar_chart(
            [(f"{r['item__item_number']} · {r['item__name'][:24]}", r["q"])
             for r in top_moving], unit="units"),
    }
    return render(request, "core/dashboard.html", context)


def company_settings(request):
    if not request.user.has_perm_code("settings.manage"):
        raise PermissionDenied
    obj = CompanySettings.load()
    form = CompanySettingsForm(request.POST or None, request.FILES or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        cache.delete("company_settings")
        audit.log(AuditLog.Action.SETTINGS, obj=obj, description="Updated company settings")
        messages.success(request, "Company settings saved.")
        return redirect("core:company_settings")
    return render(request, "core/company_settings.html", {
        "form": form, "page_title": "Company settings",
        "page_subtitle": "Name and logo used across the application, printed reports and "
                         "document print-outs.",
        "nav": "company"})


def system_settings(request):
    if not request.user.has_perm_code("settings.manage"):
        raise PermissionDenied
    obj = SystemSettings.load()
    form = SystemSettingsForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        cache.delete("system_settings")
        audit.log(AuditLog.Action.SETTINGS, obj=obj, description="Updated system settings")
        messages.success(request, "System settings saved.")
        return redirect("core:system_settings")
    return render(request, "core/system_settings.html", {
        "form": form, "page_title": "System settings", "nav": "system"})


def backup_view(request):
    if not request.user.has_perm_code("backup.manage"):
        raise PermissionDenied
    form = BackupForm(request.POST or None)
    restore_form = RestoreForm(request.POST or None, request.FILES or None)

    if request.method == "POST":
        if "create" in request.POST and form.is_valid():
            row = backup_service.create_backup(
                include_media=form.cleaned_data["include_media"],
                notes=form.cleaned_data["notes"], user=request.user)
            audit.log(AuditLog.Action.BACKUP, obj=row,
                      description=f"Created backup {row.filename}")
            messages.success(request, f"Backup {row.filename} created ({row.size_display}).")
            return redirect("core:backup")
        if "restore" in request.POST and restore_form.is_valid():
            try:
                manifest = backup_service.restore_backup(
                    restore_form.cleaned_data["file"],
                    restore_media=restore_form.cleaned_data["restore_media"],
                    user=request.user)
            except Exception as exc:  # noqa: BLE001
                messages.error(request, f"Restore failed: {exc}")
            else:
                audit.log(AuditLog.Action.RESTORE, object_type="Backup",
                          description=f"Restored backup from {manifest.get('created_at')}")
                messages.success(
                    request,
                    "Restore complete. A snapshot of the previous data was saved first.")
            return redirect("core:backup")

    return render(request, "core/backup.html", {
        "form": form, "restore_form": restore_form,
        "backups": Backup.objects.all()[:50],
        "page_title": "Backup & restore",
        "page_subtitle": "One zip holds the database and, optionally, every image and "
                         "document.",
        "nav": "backup"})


def backup_download(request, pk):
    if not request.user.has_perm_code("backup.manage"):
        raise PermissionDenied
    row = get_object_or_404(Backup, pk=pk)
    from pathlib import Path
    path = Path(row.path)
    if not path.exists():
        raise Http404("That backup file is no longer on disk.")
    audit.log(AuditLog.Action.BACKUP, obj=row, description=f"Downloaded {row.filename}")
    return FileResponse(open(path, "rb"), as_attachment=True, filename=row.filename)


def backup_delete(request, pk):
    if not request.user.has_perm_code("backup.manage"):
        raise PermissionDenied
    row = get_object_or_404(Backup, pk=pk)
    if request.method == "POST":
        name = row.filename
        backup_service.delete_backup(row)
        audit.log(AuditLog.Action.BACKUP, object_type="Backup", object_label=name,
                  description=f"Deleted backup {name}")
        messages.success(request, f"Backup {name} deleted.")
    return redirect("core:backup")


def health(request):
    """Cheap liveness probe for the load balancer."""
    from django.http import JsonResponse
    return JsonResponse({"status": "ok", "time": timezone.now().isoformat()})
