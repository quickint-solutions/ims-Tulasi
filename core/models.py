from django.core.exceptions import ValidationError
from django.db import models

from core.validators import validate_image_file
from masters.models import TimeStampedModel


class SingletonModel(models.Model):
    """One-row configuration table."""
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("This configuration record cannot be deleted.")

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class CompanySettings(SingletonModel):
    """Company identity used across the application UI and printed reports.

    The logo appears in the application shell, login page, reports and
    document print-outs only. It is deliberately NOT placed on the
    50 x 25 mm barcode label, where the space is reserved for the QR code,
    barcode and item name.
    """
    company_name = models.CharField(max_length=150, default="Spares Inventory")
    short_name = models.CharField(max_length=50, blank=True)
    logo = models.ImageField(upload_to="branding/", blank=True, null=True,
                             validators=[validate_image_file],
                             help_text="Shown in the app header, login screen and reports. "
                                       "Not printed on barcode labels.")
    address = models.TextField(blank=True)
    city = models.CharField(max_length=64, blank=True)
    state = models.CharField(max_length=64, blank=True)
    pincode = models.CharField(max_length=12, blank=True)
    country = models.CharField(max_length=64, blank=True, default="India")
    contact_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    website = models.CharField(max_length=120, blank=True)

    class Meta:
        verbose_name = "Company Settings"
        verbose_name_plural = "Company Settings"

    def __str__(self):
        return self.company_name


class SystemSettings(SingletonModel):
    """Behavioural switches (section 43 -> Settings -> System Settings)."""
    allow_negative_stock = models.BooleanField(
        default=False,
        help_text="Global default. Individual documents still need the override permission.")
    suggest_document_numbers = models.BooleanField(
        default=True,
        help_text="Pre-fill the next document number. The user can always overwrite it "
                  "(document numbers are never forced).")
    inward_prefix = models.CharField(max_length=16, blank=True, default="IN-")
    outward_prefix = models.CharField(max_length=16, blank=True, default="OUT-")
    transfer_prefix = models.CharField(max_length=16, blank=True, default="TRF-")
    adjustment_prefix = models.CharField(max_length=16, blank=True, default="ADJ-")
    opening_prefix = models.CharField(max_length=16, blank=True, default="OPN-")
    require_adjustment_approval = models.BooleanField(default=True)
    scanner_auto_focus = models.BooleanField(default=True)
    scanner_beep = models.BooleanField(default=True)
    # The QR page is a public URL that customers and visitors may open, so it
    # shows product details only. Stock quantity and warehouse/rack location are
    # internal figures and stay off unless an administrator deliberately turns
    # them on for a closed network.
    show_public_stock = models.BooleanField(
        default=False,
        verbose_name="Show stock quantity on the public QR page",
        help_text="Off by default. The QR link is public - anyone with the sticker "
                  "can open it, including customers and visitors.")
    show_public_location = models.BooleanField(
        default=False,
        verbose_name="Show warehouse and rack location on the public QR page",
        help_text="Off by default, for the same reason. Staff see the location on the "
                  "internal scanner and item pages instead.")
    public_page_enabled = models.BooleanField(
        default=True, verbose_name="Public QR page enabled")
    low_stock_banner = models.BooleanField(default=True)
    date_format = models.CharField(max_length=20, default="d-m-Y")
    rows_per_page = models.PositiveSmallIntegerField(default=50)

    class Meta:
        verbose_name = "System Settings"
        verbose_name_plural = "System Settings"

    def __str__(self):
        return "System Settings"


class Backup(TimeStampedModel):
    """A database + media snapshot (section 30)."""

    class Kind(models.TextChoices):
        MANUAL = "MANUAL", "Manual"
        SCHEDULED = "SCHEDULED", "Scheduled"
        PRE_RESTORE = "PRE_RESTORE", "Automatic pre-restore snapshot"

    filename = models.CharField(max_length=255)
    path = models.CharField(max_length=500)
    size_bytes = models.BigIntegerField(default=0)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.MANUAL)
    includes_media = models.BooleanField(default=True)
    notes = models.CharField(max_length=255, blank=True)
    checksum = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.filename

    @property
    def size_display(self):
        size = float(self.size_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.1f} {unit}"
            size /= 1024
