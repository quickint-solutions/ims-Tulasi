from django.urls import path

from . import views

app_name = "labels"

urlpatterns = [
    path("scanner/", views.scanner, name="scanner"),
    path("scanner/<int:pk>/<str:action>/", views.scanner_action, name="scanner_action"),
    path("generator/", views.barcode_generator, name="generator"),
    path("preview/", views.label_preview, name="preview"),
    path("print/", views.label_print, name="print"),
    path("print/batch/", views.batch_print, name="print_batch"),
    path("print/history/", views.PrintHistoryView.as_view(), name="print_history"),
    path("printers/", views.PrinterListView.as_view(), name="printer_list"),
    path("printers/new/", views.PrinterCreateView.as_view(), name="printer_create"),
    path("printers/<int:pk>/", views.PrinterUpdateView.as_view(), name="printer_update"),
    path("printers/<int:pk>/test/", views.test_print, name="test_print"),
    path("templates/", views.LabelTemplateListView.as_view(), name="template_list"),
    path("templates/new/", views.LabelTemplateCreateView.as_view(), name="template_create"),
    path("templates/<int:pk>/", views.LabelTemplateUpdateView.as_view(),
         name="template_update"),
]
