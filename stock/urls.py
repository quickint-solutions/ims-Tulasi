from django.urls import path

from . import views

app_name = "stock"

KINDS = ["inward", "outward", "transfer", "adjustment", "opening"]

urlpatterns = [
    path("current/", views.CurrentStockView.as_view(), name="current"),
    path("ledger/", views.StockLedgerView.as_view(), name="ledger"),
    path("low-stock/", views.LowStockView.as_view(), name="low_stock"),
    path("out-of-stock/", views.OutOfStockView.as_view(), name="out_of_stock"),
    path("location/<int:pk>/", views.location_stock, name="location_stock"),
    path("adjustment-approve/<int:pk>/", views.adjustment_approve, name="adjustment_approve"),
]

for _kind in KINDS:
    urlpatterns += [
        path(f"{_kind}/", views.document_list, {"kind": _kind}, name=f"{_kind}_list"),
        path(f"{_kind}/new/", views.document_form, {"kind": _kind}, name=f"{_kind}_create"),
        path(f"{_kind}/<int:pk>/", views.document_detail, {"kind": _kind},
             name=f"{_kind}_detail"),
        path(f"{_kind}/<int:pk>/edit/", views.document_form, {"kind": _kind},
             name=f"{_kind}_update"),
        path(f"{_kind}/<int:pk>/post/", views.document_post, {"kind": _kind},
             name=f"{_kind}_post"),
        path(f"{_kind}/<int:pk>/reverse/", views.document_cancel, {"kind": _kind},
             name=f"{_kind}_reverse"),
    ]
