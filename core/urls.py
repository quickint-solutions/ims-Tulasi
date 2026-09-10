from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("settings/company/", views.company_settings, name="company_settings"),
    path("settings/system/", views.system_settings, name="system_settings"),
    path("settings/backup/", views.backup_view, name="backup"),
    path("settings/backup/<int:pk>/download/", views.backup_download, name="backup_download"),
    path("settings/backup/<int:pk>/delete/", views.backup_delete, name="backup_delete"),
    path("healthz/", views.health, name="health"),
]
