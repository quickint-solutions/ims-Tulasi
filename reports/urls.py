from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.index, name="index"),
    path("pack/monthly/", views.export_all_monthly, name="pack_monthly"),
    path("pack/yearly/", views.export_all_yearly, name="pack_yearly"),
    path("<slug:slug>/", views.run, name="run"),
]
