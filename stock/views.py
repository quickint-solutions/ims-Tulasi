from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import DetailView, ListView

from accounts import audit
from accounts.models import AuditLog
from core.mixins import AppPermissionRequiredMixin, PageContextMixin
from core.utils import parse_date
from items.models import Item
from masters.models import ItemCategory, Location, Warehouse
from . import services
from .forms import (AdjustmentForm, AdjustmentLineFormSet, InwardForm, InwardLineFormSet,
                    OpeningForm, OpeningLineFormSet, OutwardForm, OutwardLineFormSet,
                    QuickMovementForm, QuickTransferForm, TransferForm, TransferLineFormSet)
from .models import (AdjustmentDocument, DocumentStatus, InwardDocument, MovementType,
                     OpeningStockDocument, OutwardDocument, StockBalance, StockMovement,
                     TransferDocument)

ZERO = Decimal("0")


# =====================================================================
# Stock views
# =====================================================================
class CurrentStockView(AppPermissionRequiredMixin, PageContextMixin, ListView):
    required_permission = "stock.view"
    template_name = "stock/current_stock.html"
    context_object_name = "rows"
    paginate_by = 60
    page_title = "Current stock"
    page_subtitle = "Quantity on hand by item and location. The same item can sit in many bins."
    nav = "current_stock"

    def get_queryset(self):
        g = self.request.GET
        group = g.get("group", "item")
        base = StockBalance.objects.select_related(
            "item__uom", "item__category", "warehouse", "location")
        if g.get("warehouse"):
            base = base.filter(warehouse_id=g["warehouse"])
        if g.get("location"):
            base = base.filter(location_id=g["location"])
        if g.get("category"):
            base = base.filter(Q(item__category_id=g["category"])
                               | Q(item__sub_category_id=g["category"]))
        q = g.get("q", "").strip()
        if q:
            base = base.filter(Q(item__item_number__icontains=q)
                               | Q(item__name__icontains=q)
                               | Q(item__barcode_number__icontains=q)
                               | Q(location__code__icontains=q))
        if g.get("hide_zero", "1") == "1":
            base = base.filter(quantity__gt=0)

        if group == "item":
            return (base.values("item_id", "item__item_number", "item__name",
                                "item__uom__code", "item__reorder_level",
                                "item__minimum_stock", "item__maximum_stock")
                    .annotate(qty=Sum("quantity"),
                              reserved=Sum("reserved_quantity"),
                              locations=Count("location", distinct=True))
                    .order_by("item__item_number"))
        return base.order_by("item__item_number", "warehouse__name", "location__code")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["group"] = self.request.GET.get("group", "item")
        ctx["warehouses"] = self.request.user.warehouse_queryset()
        ctx["categories"] = ItemCategory.objects.filter(is_active=True)
        totals = StockBalance.objects.aggregate(q=Sum("quantity"))
        ctx["grand_total"] = totals["q"] or ZERO
        return ctx


class StockLedgerView(AppPermissionRequiredMixin, PageContextMixin, ListView):
    required_permission = "stock.view"
    template_name = "stock/ledger.html"
    context_object_name = "movements"
    paginate_by = 100
    page_title = "Stock ledger"
    page_subtitle = "Every movement ever posted. Rows are never deleted - only reversed."
    nav = "ledger"

    def get_queryset(self):
        qs = StockMovement.objects.select_related(
            "item__uom", "warehouse", "location", "user")
        g = self.request.GET
        if g.get("item"):
            qs = qs.filter(item_id=g["item"])
        if g.get("warehouse"):
            qs = qs.filter(warehouse_id=g["warehouse"])
        if g.get("location"):
            qs = qs.filter(location_id=g["location"])
        if g.get("type"):
            qs = qs.filter(movement_type=g["type"])
        if g.get("document"):
            qs = qs.filter(document_number__icontains=g["document"])
        if g.get("user"):
            qs = qs.filter(user_id=g["user"])
        q = g.get("q", "").strip()
        if q:
            qs = qs.filter(Q(item__item_number__icontains=q) | Q(item__name__icontains=q)
                           | Q(document_number__icontains=q) | Q(party__icontains=q))
        return qs.between(parse_date(g.get("date_from")), parse_date(g.get("date_to")))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["warehouses"] = self.request.user.warehouse_queryset()
        ctx["movement_types"] = MovementType.choices
        agg = self.get_queryset().aggregate(
            inward=Sum("quantity", filter=Q(direction=1)),
            outward=Sum("quantity", filter=Q(direction=-1)))
        ctx["total_in"] = agg["inward"] or ZERO
        ctx["total_out"] = agg["outward"] or ZERO
        return ctx


class LowStockView(AppPermissionRequiredMixin, PageContextMixin, ListView):
    required_permission = "stock.view"
    template_name = "stock/low_stock.html"
    context_object_name = "items"
    paginate_by = 60
    page_title = "Low stock"
    page_subtitle = "Items at or below their reorder level. Quantity-based only."
    nav = "low_stock"
    out_of_stock = False

    def get_queryset(self):
        qs = (Item.objects.filter(is_active=True)
              .select_related("uom", "category")
              .annotate(qty=Sum("stock_balances__quantity")))
        if self.out_of_stock:
            return qs.filter(Q(qty__lte=0) | Q(qty__isnull=True)).order_by("item_number")
        return (qs.filter(qty__gt=0, reorder_level__gt=0, qty__lte=F("reorder_level"))
                .order_by("qty", "item_number"))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["out_of_stock"] = self.out_of_stock
        return ctx


class OutOfStockView(LowStockView):
    out_of_stock = True
    template_name = "stock/low_stock.html"
    page_title = "Out of stock"
    page_subtitle = "Items with zero quantity across every warehouse."
    nav = "out_of_stock"


# =====================================================================
# Document CRUD - one generic implementation, five configurations
# =====================================================================
DOC_CONFIG = {
    "inward": {
        "model": InwardDocument, "form": InwardForm, "formset": InwardLineFormSet,
        "title": "Inward", "perm": "inward.add", "nav": "inward",
        "action": AuditLog.Action.INWARD,
        "subtitle": "Receive spares into a warehouse bin. Stock increases when you post.",
    },
    "outward": {
        "model": OutwardDocument, "form": OutwardForm, "formset": OutwardLineFormSet,
        "title": "Outward", "perm": "outward.add", "nav": "outward",
        "action": AuditLog.Action.OUTWARD,
        "subtitle": "Issue spares. Posting is blocked if a bin would go below zero.",
    },
    "transfer": {
        "model": TransferDocument, "form": TransferForm, "formset": TransferLineFormSet,
        "title": "Stock transfer", "perm": "transfer.add", "nav": "transfer",
        "action": AuditLog.Action.TRANSFER,
        "subtitle": "Move stock warehouse to warehouse, or rack to rack.",
    },
    "adjustment": {
        "model": AdjustmentDocument, "form": AdjustmentForm, "formset": AdjustmentLineFormSet,
        "title": "Stock adjustment", "perm": "adjustment.add", "nav": "adjustment",
        "action": AuditLog.Action.ADJUSTMENT,
        "subtitle": "Physical verification. Enter the counted quantity; the system works out "
                    "the difference.",
    },
    "opening": {
        "model": OpeningStockDocument, "form": OpeningForm, "formset": OpeningLineFormSet,
        "title": "Opening stock", "perm": "opening.add", "nav": "opening",
        "action": AuditLog.Action.OPENING,
        "subtitle": "Seed starting balances. They become the first rows of the ledger.",
    },
}


def _cfg(kind):
    cfg = DOC_CONFIG.get(kind)
    if cfg is None:
        raise PermissionDenied("Unknown document type.")
    return cfg


def document_list(request, kind):
    cfg = _cfg(kind)
    if not request.user.has_perm_code("stock.view"):
        raise PermissionDenied
    qs = cfg["model"].objects.all()
    g = request.GET
    if g.get("status"):
        qs = qs.filter(status=g["status"])
    if g.get("q"):
        qs = qs.filter(Q(document_number__icontains=g["q"])
                       | Q(reference_number__icontains=g["q"])
                       | Q(remarks__icontains=g["q"]))
    if g.get("warehouse"):
        field = "from_warehouse_id" if kind == "transfer" else "warehouse_id"
        qs = qs.filter(**{field: g["warehouse"]})
    d_from, d_to = parse_date(g.get("date_from")), parse_date(g.get("date_to"))
    if d_from:
        qs = qs.filter(document_date__gte=d_from)
    if d_to:
        qs = qs.filter(document_date__lte=d_to)
    # Adjustment lines record a counted quantity, not a movement quantity, so the
    # header total is only meaningful for the other four document types.
    qs = qs.annotate(line_count=Count("lines"))
    if kind != "adjustment":
        qs = qs.annotate(qty=Sum("lines__quantity"))
    else:
        qs = qs.annotate(qty=Sum("lines__physical_quantity"))

    from django.core.paginator import Paginator
    paginator = Paginator(qs.order_by("-document_date", "-id"), 50)
    page_obj = paginator.get_page(g.get("page"))
    from core.mixins import querystring_without_page
    return render(request, "stock/document_list.html", {
        "kind": kind, "cfg": cfg, "documents": page_obj.object_list,
        "page_obj": page_obj, "paginator": paginator, "is_paginated": True,
        "querystring": querystring_without_page(request),
        "page_title": f"{cfg['title']} documents", "page_subtitle": cfg["subtitle"],
        "nav": cfg["nav"], "warehouses": request.user.warehouse_queryset(),
        "statuses": DocumentStatus.choices,
    })


def document_form(request, kind, pk=None):
    cfg = _cfg(kind)
    if not request.user.has_perm_code(cfg["perm"]):
        raise PermissionDenied
    instance = get_object_or_404(cfg["model"], pk=pk) if pk else None
    if instance and not instance.is_editable:
        messages.warning(request, "A posted document cannot be edited. Reverse it instead.")
        return redirect(instance.get_absolute_url())

    form = cfg["form"](request.POST or None, request.FILES or None,
                       instance=instance, user=request.user)
    formset = cfg["formset"](request.POST or None, instance=instance,
                             prefix="lines")

    if request.method == "POST" and form.is_valid() and formset.is_valid():
        doc = form.save(commit=False)
        if instance is None:
            doc.created_by = request.user
        doc.updated_by = request.user
        doc.save()
        formset.instance = doc
        formset.save()
        audit.log(AuditLog.Action.CREATE if instance is None else AuditLog.Action.UPDATE,
                  obj=doc, document_number=doc.document_number,
                  description=f"{'Created' if instance is None else 'Updated'} "
                              f"{cfg['title'].lower()} draft {doc.document_number}")
        if "save_and_post" in request.POST:
            return _post_document(request, doc, cfg)
        messages.success(request, f"{cfg['title']} {doc.document_number} saved as a draft. "
                                  f"Review it, then post to move stock.")
        return redirect(doc.get_absolute_url())

    return render(request, "stock/document_form.html", {
        "kind": kind, "cfg": cfg, "form": form, "formset": formset, "document": instance,
        "page_title": (f"Edit {cfg['title'].lower()} {instance.document_number}"
                       if instance else f"New {cfg['title'].lower()}"),
        "page_subtitle": cfg["subtitle"], "nav": cfg["nav"],
    })


def document_detail(request, kind, pk):
    cfg = _cfg(kind)
    if not request.user.has_perm_code("stock.view"):
        raise PermissionDenied
    doc = get_object_or_404(cfg["model"], pk=pk)
    movements = StockMovement.objects.filter(
        document_type=kind.upper(), document_id=doc.pk
    ).select_related("item__uom", "location", "warehouse").order_by("id")
    lines = doc.lines.select_related("item__uom")
    if kind == "transfer":
        lines = lines.select_related("from_location", "to_location")
    else:
        lines = lines.select_related("location")
    return render(request, "stock/document_detail.html", {
        "kind": kind, "cfg": cfg, "document": doc, "lines": lines, "movements": movements,
        "page_title": f"{cfg['title']} {doc.document_number}",
        "nav": cfg["nav"],
    })


def _post_document(request, doc, cfg):
    try:
        services.post_document(doc, user=request.user)
    except services.InsufficientStockError as exc:
        messages.error(request, str(exc))
        return redirect(doc.get_absolute_url())
    except services.StockError as exc:
        messages.error(request, str(exc))
        return redirect(doc.get_absolute_url())
    messages.success(request, f"{cfg['title']} {doc.document_number} posted. Stock updated.")
    return redirect(doc.get_absolute_url())


def document_post(request, kind, pk):
    cfg = _cfg(kind)
    if not request.user.has_perm_code(cfg["perm"]):
        raise PermissionDenied
    if request.method != "POST":
        return redirect("stock:document_detail", kind=kind, pk=pk)
    doc = get_object_or_404(cfg["model"], pk=pk)
    return _post_document(request, doc, cfg)


def document_cancel(request, kind, pk):
    cfg = _cfg(kind)
    if not request.user.has_perm_code("stock.reverse"):
        raise PermissionDenied("You do not have permission to reverse a posted document.")
    doc = get_object_or_404(cfg["model"], pk=pk)
    if request.method != "POST":
        return redirect(doc.get_absolute_url())
    reason = request.POST.get("reason", "").strip()
    try:
        services.cancel_document(doc, user=request.user, reason=reason)
    except services.StockError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request,
                         f"{cfg['title']} {doc.document_number} reversed. The original rows "
                         f"remain in the ledger with contra entries against them.")
    return redirect(doc.get_absolute_url())


def adjustment_approve(request, pk):
    if not request.user.has_perm_code("adjustment.approve"):
        raise PermissionDenied
    doc = get_object_or_404(AdjustmentDocument, pk=pk)
    if request.method == "POST":
        from django.utils import timezone
        doc.approved_by = request.user
        doc.approved_at = timezone.now()
        doc.save(update_fields=["approved_by", "approved_at"])
        audit.log(AuditLog.Action.ADJUSTMENT, obj=doc, document_number=doc.document_number,
                  description=f"Approved adjustment {doc.document_number}")
        messages.success(request, f"Adjustment {doc.document_number} approved.")
    return redirect(doc.get_absolute_url())


def location_stock(request, pk):
    """All items sitting in one bin."""
    if not request.user.has_perm_code("stock.view"):
        raise PermissionDenied
    location = get_object_or_404(Location.objects.select_related("warehouse"), pk=pk)
    rows = (StockBalance.objects.filter(location=location, quantity__gt=0)
            .select_related("item__uom").order_by("item__item_number"))
    return render(request, "stock/location_stock.html", {
        "location": location, "rows": rows,
        "total": rows.aggregate(t=Sum("quantity"))["t"] or ZERO,
        "page_title": f"Stock at {location.code}", "nav": "locations",
    })
