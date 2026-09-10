from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, F, Q, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.decorators.cache import never_cache
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from accounts import audit
from accounts.models import AuditLog
from core.mixins import AppPermissionRequiredMixin, PageContextMixin
from core.models import SystemSettings
from labels.generators import cached_barcode_svg, cached_qr_svg
from masters.models import ItemCategory, Warehouse
from stock.models import StockBalance, StockMovement
from .forms import (CustomFieldForm, ItemDocumentFormSet, ItemForm, ItemImageFormSet,
                    ItemImportForm)
from .models import CustomFieldDefinition, Item, ItemDocument, ItemImage


class ItemListView(AppPermissionRequiredMixin, PageContextMixin, ListView):
    required_permission = "item.view"
    template_name = "items/item_list.html"
    context_object_name = "items"
    paginate_by = 50
    page_title = "Items"
    page_subtitle = "Spare part master. Part numbers are entered manually."
    nav = "items"

    def get_queryset(self):
        qs = (Item.objects.select_related("category", "sub_category", "uom")
              .annotate(qty=Sum("stock_balances__quantity"),
                        location_count=Count("stock_balances",
                                             filter=Q(stock_balances__quantity__gt=0),
                                             distinct=True)))
        g = self.request.GET
        q = g.get("q", "").strip()
        if q:
            qs = qs.filter(Q(item_number__icontains=q) | Q(name__icontains=q)
                           | Q(barcode_number__icontains=q) | Q(manufacturer__icontains=q)
                           | Q(model_number__icontains=q) | Q(material__icontains=q)
                           | Q(oem_part_number__icontains=q)
                           | Q(alternate_part_number__icontains=q)
                           | Q(drawing_number__icontains=q))
        if g.get("category"):
            qs = qs.filter(Q(category_id=g["category"]) | Q(sub_category_id=g["category"]))
        if g.get("warehouse"):
            qs = qs.filter(stock_balances__warehouse_id=g["warehouse"],
                           stock_balances__quantity__gt=0).distinct()
        status = g.get("status")
        if status == "active":
            qs = qs.filter(is_active=True)
        elif status == "inactive":
            qs = qs.filter(is_active=False)
        elif status == "out":
            qs = qs.filter(Q(qty__lte=0) | Q(qty__isnull=True))
        elif status == "low":
            qs = qs.filter(qty__gt=0, qty__lte=F("reorder_level"))
        order = g.get("order", "item_number")
        if order in ("item_number", "-item_number", "name", "-name", "qty", "-qty"):
            qs = qs.order_by(order)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["categories"] = ItemCategory.objects.filter(is_active=True).select_related("parent")
        ctx["warehouses"] = self.request.user.warehouse_queryset()
        return ctx


class ItemDetailView(AppPermissionRequiredMixin, PageContextMixin, DetailView):
    required_permission = "item.view"
    model = Item
    template_name = "items/item_detail.html"
    context_object_name = "item"
    nav = "items"

    def get_queryset(self):
        return Item.objects.select_related("category", "sub_category", "uom", "default_location")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        item = self.object
        ctx["page_title"] = item.name
        ctx["balances"] = (StockBalance.objects.filter(item=item)
                           .select_related("warehouse", "location")
                           .order_by("warehouse__name", "location__code"))
        ctx["total_quantity"] = item.total_quantity
        ctx["movements"] = (StockMovement.objects.filter(item=item)
                            .select_related("warehouse", "location", "user")[:25])
        ctx["barcode_svg"] = cached_barcode_svg(item.barcode_number,
                                                module_width=0.32, module_height=14.0)
        ctx["qr_svg"] = cached_qr_svg(item.public_url(self.request))
        ctx["public_url"] = item.public_url(self.request)
        ctx["custom_defs"] = CustomFieldDefinition.objects.filter(is_active=True)
        ctx["warehouse_totals"] = (StockBalance.objects.filter(item=item)
                                   .values("warehouse__name")
                                   .annotate(qty=Sum("quantity")).order_by("-qty"))
        return ctx


class ItemFormMixin:
    model = Item
    form_class = ItemForm
    template_name = "items/item_form.html"
    nav = "items"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.POST:
            ctx["image_formset"] = ItemImageFormSet(self.request.POST, self.request.FILES,
                                                    instance=self.object)
            ctx["doc_formset"] = ItemDocumentFormSet(self.request.POST, self.request.FILES,
                                                     instance=self.object, prefix="docs")
        else:
            ctx["image_formset"] = ItemImageFormSet(instance=self.object)
            ctx["doc_formset"] = ItemDocumentFormSet(instance=self.object, prefix="docs")
        return ctx

    def form_valid(self, form):
        ctx = self.get_context_data()
        images, docs = ctx["image_formset"], ctx["doc_formset"]
        form.instance.updated_by = self.request.user
        if not form.instance.pk:
            form.instance.created_by = self.request.user
        self.object = form.save()
        images.instance = docs.instance = self.object
        if not (images.is_valid() and docs.is_valid()):
            return self.render_to_response(self.get_context_data(form=form))
        images.save()
        docs.save()
        return redirect(self.object.get_absolute_url())


class ItemCreateView(ItemFormMixin, AppPermissionRequiredMixin, PageContextMixin, CreateView):
    required_permission = "item.add"
    page_title = "New item"
    page_subtitle = "Enter the part number manually - no yearly numbering is imposed."

    def form_valid(self, form):
        response = super().form_valid(form)
        audit.log(AuditLog.Action.CREATE, obj=self.object,
                  description=f"Created item {self.object.item_number}")
        messages.success(self.request,
                         f"Item {self.object.item_number} created. Barcode "
                         f"{self.object.barcode_number} is ready to print.")
        return response


class ItemUpdateView(ItemFormMixin, AppPermissionRequiredMixin, PageContextMixin, UpdateView):
    required_permission = "item.change"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = f"Edit {self.object.item_number}"
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        audit.log(AuditLog.Action.UPDATE, obj=self.object,
                  description=f"Updated item {self.object.item_number}",
                  changes={f: str(form.cleaned_data.get(f)) for f in form.changed_data})
        messages.success(self.request, f"Item {self.object.item_number} updated.")
        return response


class ItemHistoryView(AppPermissionRequiredMixin, PageContextMixin, ListView):
    required_permission = "stock.view"
    template_name = "items/item_history.html"
    context_object_name = "movements"
    paginate_by = 100
    nav = "items"

    def get_queryset(self):
        self.item = get_object_or_404(Item, pk=self.kwargs["pk"])
        qs = (StockMovement.objects.filter(item=self.item)
              .select_related("warehouse", "location", "user"))
        g = self.request.GET
        if g.get("type"):
            qs = qs.filter(movement_type=g["type"])
        if g.get("warehouse"):
            qs = qs.filter(warehouse_id=g["warehouse"])
        from core.utils import parse_date
        d_from, d_to = parse_date(g.get("date_from")), parse_date(g.get("date_to"))
        return qs.between(d_from, d_to)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["item"] = self.item
        ctx["page_title"] = f"History: {self.item.item_number}"
        ctx["balances"] = (StockBalance.objects.filter(item=self.item)
                           .select_related("warehouse", "location"))
        ctx["warehouses"] = Warehouse.objects.filter(is_active=True)
        from stock.models import MovementType
        ctx["movement_types"] = MovementType.choices
        return ctx


@never_cache
def public_item(request, token):
    """Mobile page opened by scanning the QR code (sections 21, 13).

    Reached with an opaque token, never an internal id, and it never exposes
    admin data, suppliers, users or internal documents.
    """
    settings_row = SystemSettings.load()
    if not settings_row.public_page_enabled:
        raise Http404
    item = get_object_or_404(
        Item.objects.select_related("category", "sub_category", "uom"),
        qr_token=token, is_active=True)
    balances = (StockBalance.objects.filter(item=item, quantity__gt=0)
                .select_related("warehouse", "location")
                .order_by("warehouse__name", "location__code"))
    return render(request, "items/public_item.html", {
        "item": item,
        # Stock quantity and bin location are internal figures. They stay off this
        # page unless an administrator switched them on for a closed network.
        "balances": balances if settings_row.show_public_location else [],
        "total_quantity": item.total_quantity,
        "show_stock": settings_row.show_public_stock,
        "show_location": settings_row.show_public_location,
        "documents": item.documents.filter(is_public=True),
        "custom_defs": CustomFieldDefinition.objects.filter(is_active=True,
                                                            show_on_public_page=True),
        "barcode_svg": cached_barcode_svg(item.barcode_number, module_width=0.3,
                                          module_height=12.0),
        "logged_in": request.user.is_authenticated,
    })


def global_search(request):
    """Search bar and barcode-scanner entry point (section 32).

    An exact barcode or item-number hit jumps straight to the item, which is
    what makes a hardware scanner feel instant.
    """
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    q = request.GET.get("q", "").strip()
    if not q:
        return redirect("items:list")
    exact = Item.objects.filter(
        Q(barcode_number__iexact=q) | Q(item_number__iexact=q)).first()
    if exact:
        return redirect(exact.get_absolute_url())
    return redirect(f"{reverse('items:list')}?q={q}")


class FileLibraryView(AppPermissionRequiredMixin, PageContextMixin, ListView):
    required_permission = "file.view"
    template_name = "items/file_library.html"
    context_object_name = "rows"
    paginate_by = 60
    nav = "files"

    def get_queryset(self):
        kind = self.request.GET.get("kind", "images")
        q = self.request.GET.get("q", "").strip()
        if kind == "documents":
            qs = ItemDocument.objects.select_related("item").order_by("-created_at")
            if q:
                qs = qs.filter(Q(item__item_number__icontains=q) | Q(item__name__icontains=q)
                               | Q(title__icontains=q))
        else:
            qs = ItemImage.objects.select_related("item").order_by("-created_at")
            if q:
                qs = qs.filter(Q(item__item_number__icontains=q) | Q(item__name__icontains=q))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        kind = self.request.GET.get("kind", "images")
        ctx["kind"] = kind
        ctx["page_title"] = "Documents" if kind == "documents" else "Product images"
        return ctx


class CustomFieldListView(AppPermissionRequiredMixin, PageContextMixin, ListView):
    required_permission = "settings.manage"
    model = CustomFieldDefinition
    template_name = "items/custom_field_list.html"
    context_object_name = "fields"
    page_title = "Custom item fields"
    page_subtitle = "Add your own fields to the item master without changing code."
    nav = "items"


class CustomFieldCreateView(AppPermissionRequiredMixin, PageContextMixin, CreateView):
    required_permission = "settings.manage"
    model = CustomFieldDefinition
    form_class = CustomFieldForm
    template_name = "masters/master_form.html"
    success_url = reverse_lazy("items:custom_fields")
    page_title = "New custom field"
    nav = "items"


class CustomFieldUpdateView(AppPermissionRequiredMixin, PageContextMixin, UpdateView):
    required_permission = "settings.manage"
    model = CustomFieldDefinition
    form_class = CustomFieldForm
    template_name = "masters/master_form.html"
    success_url = reverse_lazy("items:custom_fields")
    page_title = "Edit custom field"
    nav = "items"


def item_import(request):
    if not request.user.has_perm_code("item.import"):
        raise PermissionDenied
    from .importexport import import_items, read_rows
    form = ItemImportForm(request.POST or None, request.FILES or None)
    result = None
    if request.method == "POST" and form.is_valid():
        try:
            rows = read_rows(form.cleaned_data["file"])
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f"The file could not be read: {exc}")
            rows = []
        if rows:
            result = import_items(
                rows, user=request.user,
                create_categories=form.cleaned_data["create_missing_categories"],
                create_locations=form.cleaned_data["create_missing_locations"],
                update_existing=form.cleaned_data["update_existing"],
                opening_document_number=form.cleaned_data["opening_document_number"],
                opening_warehouse=form.cleaned_data["opening_warehouse"])
            audit.log(AuditLog.Action.IMPORT, object_type="Item",
                      description=(f"Imported item master: {result['created']} created, "
                                   f"{result['updated']} updated, "
                                   f"{result['skipped']} skipped"))
            messages.success(
                request,
                f"{result['created']} items created, {result['updated']} updated, "
                f"{result['skipped']} skipped.")
            if result.get("opening_document"):
                messages.info(
                    request,
                    f"Opening stock document {result['opening_document'].document_number} "
                    f"was created as a draft with {result['opening_lines']} lines. "
                    f"Review and post it to bring the quantities into stock.")
        elif not rows and form.is_valid():
            messages.warning(request, "No usable rows were found in that file.")
    return render(request, "items/item_import.html", {
        "form": form, "result": result, "page_title": "Import item master",
        "page_subtitle": "Excel or CSV. Quantities only - no price columns are read.",
        "nav": "items"})


def item_import_template(request):
    if not request.user.has_perm_code("item.import"):
        raise PermissionDenied
    from core.excel import excel_response
    from .importexport import COLUMNS
    sample = [["SP-001", "BOILER FEED PUMP IMPELLER", "Pump Spares", "Impellers", "",
               "KSB", "ABC-125", "SS 316", "", 12.5, "KG", "250", "MM", "Silver",
               "Mechanical", "Boiler feed pump", "", "DRG-1021", "OEM-9911", "",
               "NOS", 2, 20, 4, "SP-001", "", "Main Warehouse", "RACK-A", "C-01",
               "T-03", 18]]
    return excel_response([{
        "name": "Item Master", "title": "Item master import template",
        "subtitle": "Fill in one row per item. Only Item Number, Item Name, Category and "
                    "UOM are required. Opening Quantity is optional.",
        "columns": [(c, i, "num" if c in ("Weight", "Minimum Stock", "Maximum Stock",
                                          "Reorder Level", "Opening Quantity") else "text")
                    for i, c in enumerate(COLUMNS)],
        "rows": sample,
    }], "item_master_template.xlsx")


def item_export(request):
    if not request.user.has_perm_code("item.export"):
        raise PermissionDenied
    from core.excel import excel_response
    from .importexport import COLUMNS, export_rows
    qs = Item.objects.all()
    if request.GET.get("category"):
        qs = qs.filter(Q(category_id=request.GET["category"])
                       | Q(sub_category_id=request.GET["category"]))
    if request.GET.get("status") == "active":
        qs = qs.filter(is_active=True)
    rows = export_rows(qs.order_by("item_number"))
    audit.log(AuditLog.Action.EXPORT, object_type="Item",
              description=f"Exported {len(rows)} items to Excel")
    from django.utils import timezone as tz
    return excel_response([{
        "name": "Item Master",
        "title": "Item master",
        "subtitle": f"Exported {tz.localtime().strftime('%d-%m-%Y %H:%M')} · "
                    f"{len(rows)} items · quantities only",
        "columns": [(c, i, "num" if c in ("Weight", "Minimum Stock", "Maximum Stock",
                                          "Reorder Level", "Opening Quantity") else "text")
                    for i, c in enumerate(COLUMNS)],
        "rows": rows,
    }], f"item_master_{tz.localdate():%Y%m%d}.xlsx")


def barcode_lookup(request):
    """JSON endpoint used by the scanner screen and by hardware scanners."""
    if not request.user.is_authenticated:
        return HttpResponse(status=401)
    code = request.GET.get("code", "").strip()
    item = Item.objects.filter(
        Q(barcode_number__iexact=code) | Q(item_number__iexact=code)).first()
    if item is None:
        return JsonResponse({"found": False, "message": "Barcode not registered."}, status=404)
    return JsonResponse({"found": True, "url": item.get_absolute_url(),
                         "item_number": item.item_number, "name": item.name})
