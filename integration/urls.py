from django.urls import path

from . import views

app_name = "integration"

urlpatterns = [
    path("erpnext/", views.erpnext_settings, name="erpnext"),
    path("erpnext/log/", views.sync_log, name="sync_log"),
    path("api-keys/", views.api_keys, name="api_keys"),
    path("api-keys/<int:pk>/revoke/", views.api_key_revoke, name="api_key_revoke"),
    path("api-log/", views.api_log, name="api_log"),
]
