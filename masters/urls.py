from django.urls import path

from . import views

app_name = "masters"

urlpatterns = [
    path("categories/", views.CategoryListView.as_view(), name="category_list"),
    path("categories/new/", views.CategoryCreateView.as_view(), name="category_create"),
    path("categories/<int:pk>/", views.CategoryUpdateView.as_view(), name="category_update"),

    path("warehouses/", views.WarehouseListView.as_view(), name="warehouse_list"),
    path("warehouses/new/", views.WarehouseCreateView.as_view(), name="warehouse_create"),
    path("warehouses/<int:pk>/", views.WarehouseUpdateView.as_view(), name="warehouse_update"),

    path("racks/", views.RackListView.as_view(), name="rack_list"),
    path("racks/new/", views.RackCreateView.as_view(), name="rack_create"),
    path("racks/<int:pk>/", views.RackUpdateView.as_view(), name="rack_update"),

    path("columns/", views.ColumnListView.as_view(), name="column_list"),
    path("columns/new/", views.ColumnCreateView.as_view(), name="column_create"),
    path("columns/<int:pk>/", views.ColumnUpdateView.as_view(), name="column_update"),

    path("tables/", views.TableListView.as_view(), name="table_list"),
    path("tables/new/", views.TableCreateView.as_view(), name="table_create"),
    path("tables/<int:pk>/", views.TableUpdateView.as_view(), name="table_update"),

    path("locations/", views.LocationListView.as_view(), name="location_list"),
    path("locations/new/", views.LocationCreateView.as_view(), name="location_create"),
    path("locations/<int:pk>/", views.LocationUpdateView.as_view(), name="location_update"),
    path("locations/build/", views.bulk_locations, name="bulk_locations"),

    path("uom/", views.UomListView.as_view(), name="uom_list"),
    path("uom/new/", views.UomCreateView.as_view(), name="uom_create"),
    path("uom/<int:pk>/", views.UomUpdateView.as_view(), name="uom_update"),

    path("options/racks/", views.rack_options, name="rack_options"),
    path("options/columns/", views.column_options, name="column_options"),
    path("options/tables/", views.table_options, name="table_options"),
    path("options/locations/", views.location_options, name="location_options"),
]
