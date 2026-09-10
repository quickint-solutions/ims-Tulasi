"""ERPNext REST client (section 37-38).

Deliberately thin and dependency-light: ERPNext's API is plain HTTP + JSON, so
the standard library is enough. The application is fully functional with the
integration disabled - nothing here is on a critical path.

Quantity only: stock is pushed as `actual_qty` / Stock Entry quantities. No
rate, valuation or amount field is ever sent or read.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from django.utils import timezone

from .models import ErpNextSettings, SyncLog


class ErpNextError(Exception):
    pass


class ErpNextClient:
    def __init__(self, settings_row=None):
        self.settings = settings_row or ErpNextSettings.load()
        if not self.settings.is_configured:
            raise ErpNextError("ERPNext URL, API key and API secret are not configured.")

    # -- low level ---------------------------------------------------------
    def _request(self, method, path, params=None, payload=None):
        url = self.settings.base_url.rstrip("/") + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization",
                       f"token {self.settings.api_key}:{self.settings.api_secret}")
        req.add_header("Accept", "application/json")
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            ctx = None
            if not self.settings.verify_ssl:
                import ssl
                ctx = ssl._create_unverified_context()  # noqa: S323 - opt-in only
            with urllib.request.urlopen(req, timeout=self.settings.timeout_seconds,
                                        context=ctx) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise ErpNextError(f"ERPNext returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ErpNextError(f"Could not reach ERPNext: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise ErpNextError("ERPNext returned a response that was not JSON.") from exc

    def get_list(self, doctype, fields=None, filters=None, limit=100):
        params = {"limit_page_length": limit}
        if fields:
            params["fields"] = json.dumps(fields)
        if filters:
            params["filters"] = json.dumps(filters)
        return self._request("GET", f"/api/resource/{doctype}", params=params).get("data", [])

    def upsert(self, doctype, name, payload):
        existing = self.get_list(doctype, fields=["name"],
                                 filters=[[doctype, "name", "=", name]], limit=1)
        if existing:
            return self._request("PUT", f"/api/resource/{doctype}/"
                                        f"{urllib.parse.quote(name)}", payload=payload)
        payload = dict(payload, **{"doctype": doctype})
        return self._request("POST", f"/api/resource/{doctype}", payload=payload)

    # -- operations --------------------------------------------------------
    def test_connection(self):
        started = time.monotonic()
        try:
            data = self._request("GET", "/api/method/frappe.auth.get_logged_user")
            user = data.get("message", "unknown")
            ok, message = True, f"Connected to ERPNext as {user}."
        except ErpNextError as exc:
            ok, message = False, str(exc)
        duration = int((time.monotonic() - started) * 1000)

        ErpNextSettings.objects.filter(pk=1).update(
            last_connection_ok=ok, last_connection_at=timezone.now(),
            last_connection_message=message[:255])
        SyncLog.objects.create(direction=SyncLog.Direction.TEST, entity="Connection",
                               status=SyncLog.Status.SUCCESS if ok else SyncLog.Status.FAILED,
                               message=message, duration_ms=duration)
        return ok, message

    def push_items(self, queryset):
        ok = failed = 0
        errors = []
        for item in queryset:
            payload = {
                "item_code": item.item_number,
                "item_name": item.name[:140],
                "description": item.description or item.name,
                "item_group": (item.category.name if item.category_id else "All Item Groups"),
                "stock_uom": item.uom.code,
                "is_stock_item": 1,
                "disabled": 0 if item.is_active else 1,
                "barcodes": [{"barcode": item.barcode_number, "barcode_type": "Code128"}],
                "brand": item.manufacturer or None,
                "weight_per_unit": float(item.weight) if item.weight is not None else 0,
                "weight_uom": item.weight_unit or None,
            }
            payload = {k: v for k, v in payload.items() if v is not None}
            try:
                self.upsert("Item", item.item_number, payload)
                ok += 1
            except ErpNextError as exc:
                failed += 1
                errors.append(f"{item.item_number}: {exc}")
        return ok, failed, errors

    def push_warehouses(self, queryset):
        ok = failed = 0
        errors = []
        for wh in queryset:
            payload = {"warehouse_name": wh.name, "company": self.settings.company}
            try:
                self.upsert("Warehouse", wh.name, payload)
                ok += 1
            except ErpNextError as exc:
                failed += 1
                errors.append(f"{wh.name}: {exc}")
        return ok, failed, errors

    def push_categories(self, queryset):
        ok = failed = 0
        errors = []
        for cat in queryset:
            payload = {"item_group_name": cat.name,
                       "parent_item_group": (cat.parent.name if cat.parent_id
                                             else "All Item Groups"),
                       "is_group": 1 if cat.children.exists() else 0}
            try:
                self.upsert("Item Group", cat.name, payload)
                ok += 1
            except ErpNextError as exc:
                failed += 1
                errors.append(f"{cat.name}: {exc}")
        return ok, failed, errors

    def push_stock_entry(self, document, entry_type):
        """Push one posted document as an ERPNext Stock Entry - quantities only."""
        rows = []
        for line in document.lines.select_related("item", "location"):
            row = {"item_code": line.item.item_number, "qty": float(line.quantity),
                   "uom": line.item.uom.code, "conversion_factor": 1}
            if entry_type == "Material Receipt":
                row["t_warehouse"] = self._wh(getattr(line, "location", None))
            elif entry_type == "Material Issue":
                row["s_warehouse"] = self._wh(getattr(line, "location", None))
            else:
                row["s_warehouse"] = self._wh(getattr(line, "from_location", None))
                row["t_warehouse"] = self._wh(getattr(line, "to_location", None))
            rows.append(row)
        payload = {
            "doctype": "Stock Entry",
            "stock_entry_type": entry_type,
            "company": self.settings.company,
            "posting_date": document.document_date.isoformat(),
            "remarks": f"{document.document_number} (Spares Inventory)",
            "items": rows,
        }
        return self._request("POST", "/api/resource/Stock Entry", payload=payload)

    def _wh(self, location):
        if location is None:
            return self.settings.default_warehouse
        return location.warehouse.name or self.settings.default_warehouse


def run_sync(*, user=None, entities=None):
    """Push the enabled masters to ERPNext and record a SyncLog per entity."""
    settings_row = ErpNextSettings.load()
    if not settings_row.is_enabled:
        raise ErpNextError("ERPNext integration is disabled.")
    if settings_row.sync_mode == ErpNextSettings.SyncMode.PULL:
        raise ErpNextError("Sync mode is set to pull-only; nothing is pushed from here.")

    client = ErpNextClient(settings_row)
    from items.models import Item
    from masters.models import ItemCategory, Warehouse

    plan = []
    if settings_row.sync_categories and (not entities or "categories" in entities):
        plan.append(("Item Group", client.push_categories,
                     ItemCategory.objects.filter(is_active=True)))
    if settings_row.sync_warehouses and (not entities or "warehouses" in entities):
        plan.append(("Warehouse", client.push_warehouses,
                     Warehouse.objects.filter(is_active=True)))
    if settings_row.sync_items and (not entities or "items" in entities):
        plan.append(("Item", client.push_items,
                     Item.objects.filter(is_active=True).select_related("category", "uom")))

    summary = []
    for entity, fn, qs in plan:
        started = time.monotonic()
        try:
            ok, failed, errors = fn(qs)
            status = (SyncLog.Status.SUCCESS if failed == 0
                      else (SyncLog.Status.PARTIAL if ok else SyncLog.Status.FAILED))
            message = "\n".join(errors[:20]) or f"{ok} record(s) synchronised."
        except ErpNextError as exc:
            ok, failed, status, message = 0, qs.count(), SyncLog.Status.FAILED, str(exc)
        SyncLog.objects.create(
            direction=SyncLog.Direction.PUSH, entity=entity, status=status,
            records_ok=ok, records_failed=failed, message=message[:4000],
            duration_ms=int((time.monotonic() - started) * 1000), created_by=user)
        summary.append((entity, ok, failed, status))

    ErpNextSettings.objects.filter(pk=1).update(last_sync_at=timezone.now())
    return summary
