from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from accounts import audit
from accounts.models import AuditLog
from core.mixins import AppPermissionRequiredMixin, PageContextMixin
from .forms import (BulkLocationForm, ItemCategoryForm, LocationForm, RackColumnForm,
                    RackForm, RackTableForm, UnitOfMeasureForm, WarehouseForm)
from .models import (ItemCategory, Location, Rack, RackColumn, RackTable,
                     UnitOfMeasure, Warehouse)


class MasterListView(AppPermissionRequiredMixin, PageContextMixin, ListView):
    paginate_by = 50
    search_fields = ()

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.GET.get("q", "").strip()
        if q and self.search_fields:
            cond = Q()
            for f in self.search_fields:
                cond |= Q(**{f"{f}__icontains": q})
            qs = qs.filter(cond)
        return qs


class MasterCreateView(AppPermissionRequiredMixin, PageContextMixin, CreateView):
    template_name = "masters/master_form.html"

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        response = super().form_valid(form)
        audit.log(AuditLog.Action.CREATE, obj=self.object,
                  description=f"Created {self.object._meta.verbose_name} {self.object}")
        messages.success(self.request, f"{self.object._meta.verbose_name.title()} created.")
        return response


class MasterUpdateView(AppPermissionRequiredMixin, PageContextMixin, UpdateView):
    template_name = "masters/master_form.html"

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        response = super().form_valid(form)
        audit.log(AuditLog.Action.UPDATE, obj=self.object,
                  description=f"Updated {self.object._meta.verbose_name} {self.object}",
                  changes={f: str(form.cleaned_data.get(f)) for f in form.changed_data})
        messages.success(self.request, f"{self.object._meta.verbose_name.title()} updated.")
        return response


# --------------------------------------------------------------------- Category
class CategoryListView(MasterListView):
    required_permission = "item.view"
    template_name = "masters/category_list.html"
    context_object_name = "categories"
    page_title = "Item categories"
    page_subtitle = "Categories and sub-categories. Every item must belong to one."
    nav = "categories"
    search_fields = ("name", "code")

    def get_queryset(self):
        return (ItemCategory.objects.select_related("parent")
                .annotate(item_count=Count("items", distinct=True))
                .order_by("parent__name", "name"))


class CategoryCreateView(MasterCreateView):
    required_permission = "category.manage"
    model = ItemCategory
    form_class = ItemCategoryForm
    success_url = reverse_lazy("masters:category_list")
    page_title = "New category"
    nav = "categories"


class CategoryUpdateView(MasterUpdateView):
    required_permission = "category.manage"
    model = ItemCategory
    form_class = ItemCategoryForm
    success_url = reverse_lazy("masters:category_list")
    page_title = "Edit category"
    nav = "categories"


# -------------------------------------------------------------------- Warehouse
class WarehouseListView(MasterListView):
    required_permission = "warehouse.view"
    template_name = "masters/warehouse_list.html"
    context_object_name = "warehouses"
    page_title = "Warehouses"
    page_subtitle = "Each warehouse holds its own independent stock."
    nav = "warehouses"
    search_fields = ("name", "code", "city")

    def get_queryset(self):
        return (Warehouse.objects.annotate(
            location_count=Count("locations", distinct=True),
            item_count=Count("stock_balances__item", distinct=True,
                             filter=Q(stock_balances__quantity__gt=0)),
            total_quantity=Sum("stock_balances__quantity"))
            .order_by("name"))


class WarehouseCreateView(MasterCreateView):
    required_permission = "warehouse.manage"
    model = Warehouse
    form_class = WarehouseForm
    success_url = reverse_lazy("masters:warehouse_list")
    page_title = "New warehouse"
    nav = "warehouses"


class WarehouseUpdateView(MasterUpdateView):
    required_permission = "warehouse.manage"
    model = Warehouse
    form_class = WarehouseForm
    success_url = reverse_lazy("masters:warehouse_list")
    page_title = "Edit warehouse"
    nav = "warehouses"


# ------------------------------------------------------------------------- Rack
class RackListView(MasterListView):
    required_permission = "location.view"
    template_name = "masters/rack_list.html"
    context_object_name = "racks"
    page_title = "Racks"
    nav = "racks"
    search_fields = ("code", "name")

    def get_queryset(self):
        qs = (Rack.objects.select_related("warehouse")
              .annotate(column_count=Count("columns", distinct=True)))
        if self.request.GET.get("warehouse"):
            qs = qs.filter(warehouse_id=self.request.GET["warehouse"])
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["warehouses"] = Warehouse.objects.filter(is_active=True)
        return ctx


class RackCreateView(MasterCreateView):
    required_permission = "location.manage"
    model = Rack
    form_class = RackForm
    success_url = reverse_lazy("masters:rack_list")
    page_title = "New rack"
    nav = "racks"


class RackUpdateView(MasterUpdateView):
    required_permission = "location.manage"
    model = Rack
    form_class = RackForm
    success_url = reverse_lazy("masters:rack_list")
    page_title = "Edit rack"
    nav = "racks"


# ----------------------------------------------------------------------- Column
class ColumnListView(MasterListView):
    required_permission = "location.view"
    template_name = "masters/column_list.html"
    context_object_name = "columns"
    page_title = "Columns"
    nav = "columns"
    search_fields = ("code", "name")

    def get_queryset(self):
        qs = (RackColumn.objects.select_related("rack__warehouse")
              .annotate(table_count=Count("tables", distinct=True)))
        if self.request.GET.get("rack"):
            qs = qs.filter(rack_id=self.request.GET["rack"])
        if self.request.GET.get("warehouse"):
            qs = qs.filter(rack__warehouse_id=self.request.GET["warehouse"])
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["warehouses"] = Warehouse.objects.filter(is_active=True)
        return ctx


class ColumnCreateView(MasterCreateView):
    required_permission = "location.manage"
    model = RackColumn
    form_class = RackColumnForm
    success_url = reverse_lazy("masters:column_list")
    page_title = "New column"
    nav = "columns"


class ColumnUpdateView(MasterUpdateView):
    required_permission = "location.manage"
    model = RackColumn
    form_class = RackColumnForm
    success_url = reverse_lazy("masters:column_list")
    page_title = "Edit column"
    nav = "columns"


# ------------------------------------------------------------------------ Table
class TableListView(MasterListView):
    required_permission = "location.view"
    template_name = "masters/table_list.html"
    context_object_name = "tables"
    page_title = "Tables"
    nav = "tables"
    search_fields = ("code", "name")

    def get_queryset(self):
        qs = RackTable.objects.select_related("column__rack__warehouse")
        if self.request.GET.get("column"):
            qs = qs.filter(column_id=self.request.GET["column"])
        if self.request.GET.get("warehouse"):
            qs = qs.filter(column__rack__warehouse_id=self.request.GET["warehouse"])
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["warehouses"] = Warehouse.objects.filter(is_active=True)
        return ctx


class TableCreateView(MasterCreateView):
    required_permission = "location.manage"
    model = RackTable
    form_class = RackTableForm
    success_url = reverse_lazy("masters:table_list")
    page_title = "New table"
    nav = "tables"


class TableUpdateView(MasterUpdateView):
    required_permission = "location.manage"
    model = RackTable
    form_class = RackTableForm
    success_url = reverse_lazy("masters:table_list")
    page_title = "Edit table"
    nav = "tables"


# --------------------------------------------------------------------- Location
class LocationListView(MasterListView):
    required_permission = "location.view"
    template_name = "masters/location_list.html"
    context_object_name = "locations"
    page_title = "Locations"
    page_subtitle = "Warehouse / Rack / Column / Table - the addressable bin for every item."
    nav = "locations"
    search_fields = ("code", "description")

    def get_queryset(self):
        qs = (Location.objects.select_related("warehouse", "rack", "column", "table")
              .annotate(item_count=Count("stock_balances",
                                         filter=Q(stock_balances__quantity__gt=0)),
                        total_quantity=Sum("stock_balances__quantity")))
        g = self.request.GET
        for param, field in (("warehouse", "warehouse_id"), ("rack", "rack_id"),
                             ("column", "column_id"), ("table", "table_id")):
            if g.get(param):
                qs = qs.filter(**{field: g[param]})
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["warehouses"] = Warehouse.objects.filter(is_active=True)
        return ctx


class LocationCreateView(MasterCreateView):
    required_permission = "location.manage"
    model = Location
    form_class = LocationForm
    success_url = reverse_lazy("masters:location_list")
    page_title = "New location"
    nav = "locations"


class LocationUpdateView(MasterUpdateView):
    required_permission = "location.manage"
    model = Location
    form_class = LocationForm
    success_url = reverse_lazy("masters:location_list")
    page_title = "Edit location"
    nav = "locations"


class UomListView(MasterListView):
    required_permission = "item.view"
    template_name = "masters/uom_list.html"
    context_object_name = "uoms"
    model = UnitOfMeasure
    page_title = "Units of measure"
    nav = "categories"
    search_fields = ("code", "name")


class UomCreateView(MasterCreateView):
    required_permission = "category.manage"
    model = UnitOfMeasure
    form_class = UnitOfMeasureForm
    success_url = reverse_lazy("masters:uom_list")
    page_title = "New unit of measure"
    nav = "categories"


class UomUpdateView(MasterUpdateView):
    required_permission = "category.manage"
    model = UnitOfMeasure
    form_class = UnitOfMeasureForm
    success_url = reverse_lazy("masters:uom_list")
    page_title = "Edit unit of measure"
    nav = "categories"


# ----------------------------------------------------------- Bulk grid builder
def bulk_locations(request):
    if not request.user.has_perm_code("location.manage"):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    form = BulkLocationForm(request.POST or None)
    created = None
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        wh = data["warehouse"]
        n_cols, n_tabs = data["columns_per_rack"], data["tables_per_column"]
        counts = {"racks": 0, "columns": 0, "tables": 0, "locations": 0}
        with transaction.atomic():
            for rcode in data["rack_codes"]:
                rack, made = Rack.objects.get_or_create(
                    warehouse=wh, code=rcode, defaults={"created_by": request.user})
                counts["racks"] += int(made)
                if n_cols == 0:
                    if data["create_locations"]:
                        _, m = Location.objects.get_or_create(
                            warehouse=wh, rack=rack, column=None, table=None,
                            defaults={"code": f"{wh.code}/{rcode}", "created_by": request.user})
                        counts["locations"] += int(m)
                    continue
                for ci in range(1, n_cols + 1):
                    col, made = RackColumn.objects.get_or_create(
                        rack=rack, code=f"C-{ci:02d}", defaults={"created_by": request.user})
                    counts["columns"] += int(made)
                    if n_tabs == 0:
                        if data["create_locations"]:
                            _, m = Location.objects.get_or_create(
                                warehouse=wh, rack=rack, column=col, table=None,
                                defaults={"code": f"{wh.code}/{rcode}/{col.code}",
                                          "created_by": request.user})
                            counts["locations"] += int(m)
                        continue
                    for ti in range(1, n_tabs + 1):
                        tab, made = RackTable.objects.get_or_create(
                            column=col, code=f"T-{ti:02d}",
                            defaults={"created_by": request.user})
                        counts["tables"] += int(made)
                        if data["create_locations"]:
                            _, m = Location.objects.get_or_create(
                                warehouse=wh, rack=rack, column=col, table=tab,
                                defaults={"code": f"{wh.code}/{rcode}/{col.code}/{tab.code}",
                                          "created_by": request.user})
                            counts["locations"] += int(m)
        audit.log(AuditLog.Action.CREATE, object_type="Location",
                  description=f"Bulk-created rack grid in {wh.name}: {counts}")
        messages.success(
            request,
            f"Created {counts['racks']} racks, {counts['columns']} columns, "
            f"{counts['tables']} tables and {counts['locations']} locations in {wh.name}.")
        return redirect("masters:location_list")
    return render(request, "masters/bulk_locations.html", {
        "form": form, "created": created, "page_title": "Build rack grid",
        "page_subtitle": "Create a whole rack / column / table structure in one step.",
        "nav": "locations"})


# --------------------------------------------------------- AJAX option endpoints
def _options(request, queryset, label=str):
    return JsonResponse({"results": [{"id": o.pk, "text": label(o)} for o in queryset]})


def rack_options(request):
    wh = request.GET.get("warehouse")
    qs = Rack.objects.filter(is_active=True)
    qs = qs.filter(warehouse_id=wh) if wh else qs.none()
    return _options(request, qs.order_by("code"), lambda o: o.code)


def column_options(request):
    rack = request.GET.get("rack")
    qs = RackColumn.objects.filter(is_active=True)
    qs = qs.filter(rack_id=rack) if rack else qs.none()
    return _options(request, qs.order_by("code"), lambda o: o.code)


def table_options(request):
    col = request.GET.get("column")
    qs = RackTable.objects.filter(is_active=True)
    qs = qs.filter(column_id=col) if col else qs.none()
    return _options(request, qs.order_by("code"), lambda o: o.code)


def location_options(request):
    g = request.GET
    qs = Location.objects.filter(is_active=True).select_related("warehouse")
    if g.get("warehouse"):
        qs = qs.filter(warehouse_id=g["warehouse"])
    else:
        return JsonResponse({"results": []})
    for param, field in (("rack", "rack_id"), ("column", "column_id"), ("table", "table_id")):
        if g.get(param):
            qs = qs.filter(**{field: g[param]})
    return _options(request, qs.order_by("code")[:500], lambda o: o.code)
