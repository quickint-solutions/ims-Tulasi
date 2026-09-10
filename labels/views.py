from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView

from accounts import audit
from accounts.models import AuditLog
from core.mixins import AppPermissionRequiredMixin, PageContextMixin
from core.models import SystemSettings
from items.models import Item
from masters.models import Location
from stock import services
from stock.models import (InwardDocument, InwardItem, OutwardDocument, OutwardItem,
                          StockBalance, StockMovement, TransferDocument, TransferItem)
from stock.forms import QuickMovementForm, QuickTransferForm
from .forms import BatchPrintForm, LabelPreviewForm, LabelTemplateForm, PrinterSettingForm
from .models import LabelPrintLog, LabelTemplate, PrinterSetting
from .render import label_context

ZERO = Decimal("0")


# ------------------------------------------------------------------ Scanner
def scanner(request):
    """Full-screen scanner-first workflow (sections 19, 20, 46, 47)."""
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    if not request.user.has_perm_code("scanner.use"):
        raise PermissionDenied
    code = (request.GET.get("code") or "").strip()
    item = None
    balances = []
    if code:
        item = Item.objects.filter(
            Q(barcode_number__iexact=code) | Q(item_number__iexact=code)
        ).select_related("category", "uom").first()
        if item is None:
            messages.error(request, f"Barcode not registered: {code}")
        else:
            balances = (StockBalance.objects.filter(item=item, quantity__gt=0)
                        .select_related("warehouse", "location")
                        .order_by("-quantity"))
    return render(request, "labels/scanner.html", {
        "code": code, "item": item, "balances": balances,
        "total_quantity": item.total_quantity if item else ZERO,
        "recent": (StockMovement.objects.filter(item=item)
                   .select_related("location", "user")[:8]) if item else [],
        "page_title": "Inventory scanner", "nav": "scanner",
        "sys_settings": SystemSettings.load(),
    })


def scanner_action(request, pk, action):
    """One-item inward / outward / transfer straight from the scanner."""
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    item = get_object_or_404(Item, pk=pk)
    perm = {"inward": "inward.add", "outward": "outward.add",
            "transfer": "transfer.add"}.get(action)
    if perm is None or not request.user.has_perm_code(perm):
        raise PermissionDenied

    balances = (StockBalance.objects.filter(item=item, quantity__gt=0)
                .select_related("warehouse", "location").order_by("-quantity"))

    if action == "transfer":
        form = QuickTransferForm(request.POST or None, user=request.user,
                                 initial={"item_id": item.pk})
        if request.method == "POST" and form.is_valid():
            data = form.cleaned_data
            doc = TransferDocument.objects.create(
                document_number=data["document_number"].strip().upper(),
                from_warehouse=data["from_location"].warehouse,
                to_warehouse=data["to_location"].warehouse,
                remarks=data["remarks"], created_by=request.user)
            TransferItem.objects.create(document=doc, item=item,
                                        from_location=data["from_location"],
                                        to_location=data["to_location"],
                                        quantity=data["quantity"])
            try:
                services.post_document(doc, user=request.user)
            except services.StockError as exc:
                doc.delete()
                messages.error(request, str(exc))
            else:
                messages.success(request, f"Transferred {data['quantity']:g} "
                                          f"{item.uom.code} on {doc.document_number}.")
                from django.urls import reverse
                return redirect(
                    f"{reverse('labels:scanner')}?code={item.barcode_number}")
    else:
        form = QuickMovementForm(request.POST or None, user=request.user, item=item,
                                 initial={"action": action.upper(), "item_id": item.pk})
        if request.method == "POST" and form.is_valid():
            data = form.cleaned_data
            location = data["location"]
            try:
                if action == "inward":
                    doc = InwardDocument.objects.create(
                        document_number=data["document_number"].strip().upper(),
                        warehouse=location.warehouse, supplier=data["party"],
                        remarks=data["remarks"], created_by=request.user)
                    InwardItem.objects.create(document=doc, item=item, location=location,
                                              quantity=data["quantity"])
                else:
                    doc = OutwardDocument.objects.create(
                        document_number=data["document_number"].strip().upper(),
                        warehouse=location.warehouse, destination=data["party"],
                        remarks=data["remarks"], created_by=request.user)
                    OutwardItem.objects.create(document=doc, item=item, location=location,
                                               quantity=data["quantity"])
                services.post_document(doc, user=request.user)
            except services.StockError as exc:
                messages.error(request, str(exc))
                try:
                    doc.delete()
                except Exception:  # noqa: BLE001
                    pass
            else:
                messages.success(
                    request,
                    f"{action.title()} posted: {data['quantity']:g} {item.uom.code} "
                    f"of {item.item_number} on {doc.document_number}.")
                from django.urls import reverse
                return redirect(f"{reverse('labels:scanner')}?code={item.barcode_number}")

    return render(request, "labels/scanner_action.html", {
        "item": item, "action": action, "form": form, "balances": balances,
        "total_quantity": item.total_quantity,
        "page_title": f"{action.title()}: {item.item_number}", "nav": "scanner",
    })


# ------------------------------------------------------------------- Labels
def label_preview(request):
    if not request.user.has_perm_code("barcode.view"):
        raise PermissionDenied
    initial = {}
    if request.GET.get("item"):
        initial["item"] = request.GET["item"]
    form = LabelPreviewForm(request.GET or None, initial=initial)
    ctx = None
    if form.is_bound and form.is_valid():
        ctx = label_context(form.cleaned_data["item"], request,
                            form.cleaned_data.get("template"))
        ctx["copies"] = form.cleaned_data["copies"]
        ctx["printer"] = form.cleaned_data.get("printer")
        ctx["zoom"] = form.cleaned_data.get("zoom") or "3"
    return render(request, "labels/label_preview.html", {
        "form": form, "label": ctx,
        "page_title": "Label preview",
        "page_subtitle": "True 50 mm x 25 mm. What you see is what the printer produces.",
        "nav": "label_preview",
        "default_printer": PrinterSetting.get_default(),
    })


def label_print(request):
    """Renders a print-ready sheet of labels."""
    if not request.user.has_perm_code("barcode.print"):
        raise PermissionDenied
    item_ids = request.GET.getlist("item")
    copies = max(1, min(500, int(request.GET.get("copies", 1) or 1)))
    template_id = request.GET.get("template")
    printer_id = request.GET.get("printer")
    template = (LabelTemplate.objects.filter(pk=template_id).first() if template_id
                else LabelTemplate.get_default())
    printer = (PrinterSetting.objects.filter(pk=printer_id).first() if printer_id
               else PrinterSetting.get_default())
    items = Item.objects.filter(pk__in=item_ids).select_related("uom")
    if not items:
        messages.error(request, "Select at least one item to print.")
        return redirect("labels:preview")

    labels = []
    for item in items:
        ctx = label_context(item, request, template)
        labels.extend([ctx] * copies)
        LabelPrintLog.objects.create(
            item=item, template=template, printer=printer, copies=copies,
            is_reprint=item.print_logs.exists(),
            barcode_snapshot=item.barcode_number, created_by=request.user)
        audit.log(AuditLog.Action.LABEL_PRINT, obj=item,
                  quantity=copies,
                  description=f"Printed {copies} label(s) for {item.item_number}")
    return render(request, "labels/label_sheet.html", {
        "labels": labels, "template": template, "printer": printer,
        "columns": printer.columns_per_row if printer else 1,
        "gap_mm": printer.label_gap_mm if printer else 2,
        "width_mm": (template.width_mm if template else 50),
        "height_mm": (template.height_mm if template else 25),
        "auto_print": request.GET.get("auto", "1") == "1",
    })


def barcode_generator(request):
    """Assign / regenerate barcodes and see what is not yet labelled."""
    if not request.user.has_perm_code("barcode.view"):
        raise PermissionDenied
    q = request.GET.get("q", "").strip()
    qs = Item.objects.filter(is_active=True).select_related("uom")
    if q:
        qs = qs.filter(Q(item_number__icontains=q) | Q(name__icontains=q)
                       | Q(barcode_number__icontains=q))
    if request.GET.get("filter") == "unprinted":
        qs = qs.filter(print_logs__isnull=True)

    if request.method == "POST":
        if not request.user.has_perm_code("barcode.generate"):
            raise PermissionDenied
        ids = request.POST.getlist("item")
        updated = 0
        for item in Item.objects.filter(pk__in=ids):
            if item.barcode_number != item.item_number and not Item.objects.filter(
                    barcode_number=item.item_number).exclude(pk=item.pk).exists():
                item.barcode_number = item.item_number
                item.save(update_fields=["barcode_number"])
                updated += 1
        audit.log(AuditLog.Action.BARCODE, object_type="Item",
                  description=f"Reset {updated} barcodes to the item number")
        messages.success(request, f"{updated} barcode(s) reset to match the item number.")
        return redirect("labels:generator")

    from django.core.paginator import Paginator
    paginator = Paginator(qs.order_by("item_number"), 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    rows = [{"item": i, "printed": i.print_logs.exists()} for i in page_obj.object_list]
    from core.mixins import querystring_without_page
    return render(request, "labels/generator.html", {
        "rows": rows, "page_obj": page_obj, "is_paginated": True,
        "querystring": querystring_without_page(request),
        "page_title": "Barcode generator",
        "page_subtitle": "Every item carries a Code 128 barcode and a QR code for its "
                         "public detail page.",
        "nav": "barcode_gen",
    })


def batch_print(request):
    if not request.user.has_perm_code("barcode.print"):
        raise PermissionDenied
    form = BatchPrintForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        items = form.resolve_items()
        params = "&".join(f"item={i.pk}" for i in items[:500])
        extra = f"&copies={form.cleaned_data['copies']}"
        if form.cleaned_data.get("template"):
            extra += f"&template={form.cleaned_data['template'].pk}"
        if form.cleaned_data.get("printer"):
            extra += f"&printer={form.cleaned_data['printer'].pk}"
        if not params:
            messages.error(request, "That selection matched no items.")
        else:
            from django.urls import reverse
            return redirect(f"{reverse('labels:print')}?{params}{extra}")
    return render(request, "labels/batch_print.html", {
        "form": form, "page_title": "Label printing",
        "page_subtitle": "Print a roll or a sheet of 50 x 25 mm labels.",
        "nav": "label_print",
    })


def test_print(request, pk=None):
    """Send a single calibration label to the chosen printer."""
    if not request.user.has_perm_code("printer.manage"):
        raise PermissionDenied
    printer = get_object_or_404(PrinterSetting, pk=pk) if pk else PrinterSetting.get_default()
    item = Item.objects.filter(is_active=True).first()
    if item is None:
        messages.error(request, "Create at least one item before running a test print.")
        return redirect("labels:printer_list")
    ctx = label_context(item, request)
    audit.log(AuditLog.Action.LABEL_PRINT, obj=printer,
              description=f"Test print on {printer.name if printer else 'browser'}")
    return render(request, "labels/label_sheet.html", {
        "labels": [ctx], "template": LabelTemplate.get_default(), "printer": printer,
        "columns": 1, "gap_mm": printer.label_gap_mm if printer else 2,
        "width_mm": printer.label_width_mm if printer else 50,
        "height_mm": printer.label_height_mm if printer else 25,
        "auto_print": True, "is_test": True,
    })


# --------------------------------------------------------- Printer settings
class PrinterListView(AppPermissionRequiredMixin, PageContextMixin, ListView):
    required_permission = "printer.manage"
    model = PrinterSetting
    template_name = "labels/printer_list.html"
    context_object_name = "printers"
    page_title = "Printer settings"
    page_subtitle = ("Seznik Mini and any other thermal label printer. No printer model "
                     "is hard-coded.")
    nav = "printers"


class PrinterCreateView(AppPermissionRequiredMixin, PageContextMixin, CreateView):
    required_permission = "printer.manage"
    model = PrinterSetting
    form_class = PrinterSettingForm
    template_name = "masters/master_form.html"
    success_url = reverse_lazy("labels:printer_list")
    page_title = "New printer"
    nav = "printers"


class PrinterUpdateView(AppPermissionRequiredMixin, PageContextMixin, UpdateView):
    required_permission = "printer.manage"
    model = PrinterSetting
    form_class = PrinterSettingForm
    template_name = "masters/master_form.html"
    success_url = reverse_lazy("labels:printer_list")
    page_title = "Edit printer"
    nav = "printers"


class LabelTemplateListView(AppPermissionRequiredMixin, PageContextMixin, ListView):
    required_permission = "printer.manage"
    model = LabelTemplate
    template_name = "labels/template_list.html"
    context_object_name = "templates"
    page_title = "Label templates"
    nav = "label_templates"


class LabelTemplateCreateView(AppPermissionRequiredMixin, PageContextMixin, CreateView):
    required_permission = "printer.manage"
    model = LabelTemplate
    form_class = LabelTemplateForm
    template_name = "masters/master_form.html"
    success_url = reverse_lazy("labels:template_list")
    page_title = "New label template"
    nav = "label_templates"


class LabelTemplateUpdateView(AppPermissionRequiredMixin, PageContextMixin, UpdateView):
    required_permission = "printer.manage"
    model = LabelTemplate
    form_class = LabelTemplateForm
    template_name = "masters/master_form.html"
    success_url = reverse_lazy("labels:template_list")
    page_title = "Edit label template"
    nav = "label_templates"


class PrintHistoryView(AppPermissionRequiredMixin, PageContextMixin, ListView):
    required_permission = "barcode.view"
    template_name = "labels/print_history.html"
    context_object_name = "logs"
    paginate_by = 60
    page_title = "Label print history"
    nav = "barcode_gen"

    def get_queryset(self):
        qs = LabelPrintLog.objects.select_related("item", "printer", "created_by")
        if self.request.GET.get("item"):
            qs = qs.filter(item_id=self.request.GET["item"])
        return qs
