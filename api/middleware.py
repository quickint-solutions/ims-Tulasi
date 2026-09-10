import time

from .models import ApiLog


class ApiLoggingMiddleware:
    """Records every /api/ request for the API Logs screen (section 43)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith("/api/"):
            return self.get_response(request)
        started = time.monotonic()
        response = self.get_response(request)
        try:
            user = getattr(request, "user", None)
            ApiLog.objects.create(
                api_key=getattr(request, "api_key", None),
                user=user if (user and user.is_authenticated) else None,
                method=request.method[:8],
                path=request.path[:255],
                query_string=request.META.get("QUERY_STRING", "")[:500],
                status_code=response.status_code,
                duration_ms=int((time.monotonic() - started) * 1000),
                ip_address=(request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
                            or request.META.get("REMOTE_ADDR")),
            )
        except Exception:  # pragma: no cover - logging must never break the response
            pass
        return response
