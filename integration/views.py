from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from accounts import audit
from accounts.models import AuditLog
from api.models import ApiKey, ApiLog
from core.mixins import querystring_without_page
from .erpnext import ErpNextClient, ErpNextError, run_sync
from .forms import ApiKeyForm, ErpNextSettingsForm
from .models import ErpNextSettings, SyncLog


def erpnext_settings(request):
    if not request.user.has_perm_code("erpnext.manage"):
        raise PermissionDenied
    obj = ErpNextSettings.load()
    form = ErpNextSettingsForm(request.POST or None, instance=obj)

    if request.method == "POST":
        if "test" in request.POST:
            try:
                ok, message = ErpNextClient(obj).test_connection()
            except ErpNextError as exc:
                ok, message = False, str(exc)
            (messages.success if ok else messages.error)(request, message)
            return redirect("integration:erpnext")
        if "sync" in request.POST:
            if not request.user.has_perm_code("erpnext.sync"):
                raise PermissionDenied
            try:
                summary = run_sync(user=request.user)
            except ErpNextError as exc:
                messages.error(request, str(exc))
            else:
                for entity, ok, failed, status in summary:
                    line = f"{entity}: {ok} synced, {failed} failed ({status})."
                    (messages.success if failed == 0 else messages.warning)(request, line)
                audit.log(AuditLog.Action.SYNC, object_type="ERPNext",
                          description="Ran ERPNext synchronisation")
            return redirect("integration:erpnext")
        if form.is_valid():
            form.save()
            audit.log(AuditLog.Action.SETTINGS, obj=obj,
                      description="Updated ERPNext integration settings")
            messages.success(request, "ERPNext settings saved.")
            return redirect("integration:erpnext")

    return render(request, "integration/erpnext.html", {
        "form": form, "settings_row": obj,
        "recent": SyncLog.objects.all()[:10],
        "page_title": "ERPNext integration",
        "page_subtitle": "The application works normally whether this is on or off.",
        "nav": "erpnext"})


def sync_log(request):
    if not request.user.has_perm_code("erpnext.manage"):
        raise PermissionDenied
    qs = SyncLog.objects.select_related("created_by")
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    if request.GET.get("entity"):
        qs = qs.filter(entity__icontains=request.GET["entity"])
    paginator = Paginator(qs, 60)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "integration/sync_log.html", {
        "logs": page_obj.object_list, "page_obj": page_obj, "is_paginated": True,
        "querystring": querystring_without_page(request),
        "statuses": SyncLog.Status.choices,
        "page_title": "ERPNext sync log", "nav": "sync_log"})


def api_keys(request):
    if not request.user.has_perm_code("api.manage"):
        raise PermissionDenied
    form = ApiKeyForm(request.POST or None)
    new_key = None
    if request.method == "POST" and form.is_valid():
        scopes = ["read", "write"] if form.cleaned_data["can_write"] else ["read"]
        obj, raw = ApiKey.issue(
            name=form.cleaned_data["name"], user=form.cleaned_data["user"], scopes=scopes,
            allowed_ips=form.cleaned_data["allowed_ips"],
            rate_limit=form.cleaned_data["rate_limit"],
            expires_at=form.cleaned_data["expires_at"],
            is_active=form.cleaned_data["is_active"], created_by=request.user)
        new_key = raw
        audit.log(AuditLog.Action.SETTINGS, obj=obj,
                  description=f"Issued API key {obj.name}")
        messages.success(request, "API key created. Copy it now - it is not shown again.")
        form = ApiKeyForm()
    return render(request, "integration/api_keys.html", {
        "form": form, "new_key": new_key,
        "keys": ApiKey.objects.select_related("user"),
        "page_title": "API keys",
        "page_subtitle": "Server-to-server credentials for the REST API. Only a hash is "
                         "stored.",
        "nav": "api_keys"})


def api_key_revoke(request, pk):
    if not request.user.has_perm_code("api.manage"):
        raise PermissionDenied
    key = get_object_or_404(ApiKey, pk=pk)
    if request.method == "POST":
        key.is_active = False
        key.save(update_fields=["is_active"])
        audit.log(AuditLog.Action.SETTINGS, obj=key, description=f"Revoked API key {key.name}")
        messages.success(request, f"API key {key.name} revoked.")
    return redirect("integration:api_keys")


def api_log(request):
    if not request.user.has_perm_code("api.manage"):
        raise PermissionDenied
    qs = ApiLog.objects.select_related("api_key", "user")
    if request.GET.get("status"):
        qs = qs.filter(status_code=request.GET["status"])
    if request.GET.get("path"):
        qs = qs.filter(path__icontains=request.GET["path"])
    paginator = Paginator(qs, 100)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "integration/api_log.html", {
        "logs": page_obj.object_list, "page_obj": page_obj, "is_paginated": True,
        "querystring": querystring_without_page(request),
        "page_title": "API request log", "nav": "api_log"})
