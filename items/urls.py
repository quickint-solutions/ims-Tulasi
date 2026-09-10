from django.urls import path

from . import views

app_name = "items"

urlpatterns = [
    path("", views.ItemListView.as_view(), name="list"),
    path("new/", views.ItemCreateView.as_view(), name="create"),
    path("search/", views.global_search, name="search"),
    path("lookup/", views.barcode_lookup, name="lookup"),
    path("import/", views.item_import, name="import"),
    path("import/template/", views.item_import_template, name="import_template"),
    path("export/", views.item_export, name="export"),
    path("files/", views.FileLibraryView.as_view(), name="files"),
    path("custom-fields/", views.CustomFieldListView.as_view(), name="custom_fields"),
    path("custom-fields/new/", views.CustomFieldCreateView.as_view(), name="custom_field_create"),
    path("custom-fields/<int:pk>/", views.CustomFieldUpdateView.as_view(),
         name="custom_field_update"),
    path("<int:pk>/", views.ItemDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.ItemUpdateView.as_view(), name="update"),
    path("<int:pk>/history/", views.ItemHistoryView.as_view(), name="history"),
]
