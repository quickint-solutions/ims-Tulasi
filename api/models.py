import hashlib
import secrets

from django.db import models

from masters.models import TimeStampedModel


def generate_key():
    return "sk_" + secrets.token_urlsafe(24)


class ApiKey(TimeStampedModel):
    """Server-to-server credential (section 39).

    Only a SHA-256 hash of the secret is stored; the plaintext is shown once
    at creation time and never again.
    """
    name = models.CharField(max_length=100, unique=True)
    prefix = models.CharField(max_length=12, db_index=True, editable=False)
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="api_keys",
                             help_text="Calls are authorised with this user's permissions.")
    scopes = models.JSONField(default=list, blank=True,
                              help_text='e.g. ["read", "write"]. Empty means read only.')
    allowed_ips = models.CharField(max_length=255, blank=True,
                                   help_text="Comma-separated allow-list. Empty means any IP.")
    rate_limit = models.CharField(max_length=20, blank=True, default="1000/hour")
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "API Key"

    def __str__(self):
        return f"{self.name} ({self.prefix}...)"

    @staticmethod
    def hash_key(raw):
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def issue(cls, *, name, user, scopes=None, **kwargs):
        raw = generate_key()
        obj = cls.objects.create(
            name=name, user=user, scopes=scopes or ["read"],
            prefix=raw[:12], key_hash=cls.hash_key(raw), **kwargs)
        return obj, raw

    @property
    def can_write(self):
        return "write" in (self.scopes or [])

    def is_valid(self):
        from django.utils import timezone
        if not self.is_active:
            return False
        return not (self.expires_at and self.expires_at < timezone.now())


class ApiLog(models.Model):
    """Request log for the REST API (section 43 -> Integration -> API Logs)."""
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    api_key = models.ForeignKey(ApiKey, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="logs")
    user = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="api_logs")
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=255, db_index=True)
    query_string = models.CharField(max_length=500, blank=True)
    status_code = models.PositiveSmallIntegerField(db_index=True)
    duration_ms = models.PositiveIntegerField(default=0)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["-timestamp", "status_code"])]

    def __str__(self):
        return f"{self.method} {self.path} -> {self.status_code}"
