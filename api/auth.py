from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import ApiKey


class ApiKeyAuthentication(authentication.BaseAuthentication):
    """Authenticate with `Authorization: ApiKey <key>` or the X-API-Key header."""

    keyword = "apikey"

    def authenticate(self, request):
        raw = request.META.get("HTTP_X_API_KEY", "")
        if not raw:
            header = request.META.get("HTTP_AUTHORIZATION", "")
            parts = header.split()
            if len(parts) == 2 and parts[0].lower() == self.keyword:
                raw = parts[1]
        if not raw:
            return None

        try:
            key = ApiKey.objects.select_related("user").get(key_hash=ApiKey.hash_key(raw))
        except ApiKey.DoesNotExist:
            raise exceptions.AuthenticationFailed("Invalid API key.")

        if not key.is_valid():
            raise exceptions.AuthenticationFailed("API key is inactive or expired.")
        if key.allowed_ips:
            allowed = [ip.strip() for ip in key.allowed_ips.split(",") if ip.strip()]
            client = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() \
                or request.META.get("REMOTE_ADDR")
            if client not in allowed:
                raise exceptions.AuthenticationFailed("IP address not allowed for this key.")
        if not key.user.is_active:
            raise exceptions.AuthenticationFailed("The key's user account is disabled.")

        ApiKey.objects.filter(pk=key.pk).update(last_used_at=timezone.now())
        request.api_key = key
        return (key.user, key)

    def authenticate_header(self, request):
        return "ApiKey"
