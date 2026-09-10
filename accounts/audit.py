from .middleware import get_current_request, get_current_user
from .models import AuditLog


def _client_ip(request):
    if not request:
        return None
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def log(action, *, user=None, obj=None, object_type="", object_id="", object_label="",
        document_number="", quantity=None, description="", changes=None):
    """Write an audit record. Never raises - auditing must not break a transaction."""
    try:
        request = get_current_request()
        user = user or get_current_user()
        if user is not None and not getattr(user, "is_authenticated", False):
            user = None
        if obj is not None:
            object_type = object_type or obj.__class__.__name__
            object_id = object_id or str(getattr(obj, "pk", ""))
            object_label = object_label or str(obj)[:255]
        return AuditLog.objects.create(
            user=user,
            username_snapshot=getattr(user, "username", "") or "system",
            action=action,
            object_type=object_type[:64],
            object_id=str(object_id)[:64],
            object_label=object_label[:255],
            document_number=document_number[:64],
            quantity=quantity,
            description=description,
            changes=changes or {},
            ip_address=_client_ip(request),
            user_agent=(request.META.get("HTTP_USER_AGENT", "")[:255] if request else ""),
        )
    except Exception:  # pragma: no cover - auditing is best effort
        return None
