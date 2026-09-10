from django.db import models

from core.models import SingletonModel
from masters.models import TimeStampedModel


class ErpNextSettings(SingletonModel):
    """ERPNext connection profile (section 38).

    The application is fully functional with integration disabled.
    """

    class SyncMode(models.TextChoices):
        DISABLED = "DISABLED", "Disabled"
        PUSH = "PUSH", "One way - push to ERPNext"
        PULL = "PULL", "One way - pull from ERPNext"
        TWO_WAY = "TWO_WAY", "Two way"

    is_enabled = models.BooleanField(default=False)
    base_url = models.URLField("ERPNext URL", blank=True,
                               help_text="e.g. https://erp.example.com")
    api_key = models.CharField(max_length=120, blank=True)
    api_secret = models.CharField(max_length=200, blank=True)
    company = models.CharField(max_length=150, blank=True)
    default_warehouse = models.CharField(max_length=150, blank=True,
                                         help_text="ERPNext warehouse name used as fallback.")
    sync_mode = models.CharField(max_length=10, choices=SyncMode.choices,
                                 default=SyncMode.DISABLED)
    sync_items = models.BooleanField(default=True)
    sync_categories = models.BooleanField(default=True)
    sync_warehouses = models.BooleanField(default=True)
    sync_stock = models.BooleanField(default=True)
    sync_inward = models.BooleanField(default=False)
    sync_outward = models.BooleanField(default=False)
    sync_transfer = models.BooleanField(default=False)
    verify_ssl = models.BooleanField(default=True)
    timeout_seconds = models.PositiveSmallIntegerField(default=30)
    last_connection_ok = models.BooleanField(default=False)
    last_connection_at = models.DateTimeField(null=True, blank=True)
    last_connection_message = models.CharField(max_length=255, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "ERPNext Settings"
        verbose_name_plural = "ERPNext Settings"

    def __str__(self):
        return "ERPNext Integration"

    @property
    def is_configured(self):
        return bool(self.base_url and self.api_key and self.api_secret)


class SyncLog(TimeStampedModel):
    class Direction(models.TextChoices):
        PUSH = "PUSH", "Push to ERPNext"
        PULL = "PULL", "Pull from ERPNext"
        TEST = "TEST", "Connection test"

    class Status(models.TextChoices):
        SUCCESS = "SUCCESS", "Success"
        PARTIAL = "PARTIAL", "Partial"
        FAILED = "FAILED", "Failed"

    direction = models.CharField(max_length=8, choices=Direction.choices)
    entity = models.CharField(max_length=40, blank=True,
                              help_text="Item, Warehouse, Stock, Inward, ...")
    status = models.CharField(max_length=8, choices=Status.choices)
    records_ok = models.PositiveIntegerField(default=0)
    records_failed = models.PositiveIntegerField(default=0)
    message = models.TextField(blank=True)
    payload_preview = models.TextField(blank=True)
    duration_ms = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Sync Log"

    def __str__(self):
        return f"{self.direction} {self.entity} {self.status}"
