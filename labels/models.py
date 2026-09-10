from django.db import models

from masters.models import TimeStampedModel


class PrinterSetting(TimeStampedModel):
    """Printer profile (section 18). No model is hard-coded."""

    class PrinterType(models.TextChoices):
        THERMAL_LABEL = "THERMAL_LABEL", "Thermal label printer"
        THERMAL_RECEIPT = "THERMAL_RECEIPT", "Thermal receipt printer"
        LASER = "LASER", "Laser / inkjet (label sheet)"
        OTHER = "OTHER", "Other"

    class ConnectionType(models.TextChoices):
        USB = "USB", "USB"
        BLUETOOTH = "BLUETOOTH", "Bluetooth"
        NETWORK = "NETWORK", "Network / IP"
        SYSTEM = "SYSTEM", "Windows / OS printer"
        BROWSER = "BROWSER", "Browser print dialog"

    name = models.CharField(max_length=100, unique=True,
                            help_text="e.g. Seznik Mini - Store Counter")
    printer_type = models.CharField(max_length=20, choices=PrinterType.choices,
                                    default=PrinterType.THERMAL_LABEL)
    connection_type = models.CharField(max_length=12, choices=ConnectionType.choices,
                                       default=ConnectionType.BROWSER)
    system_printer_name = models.CharField(max_length=150, blank=True,
                                           help_text="OS printer queue name, if applicable.")
    network_address = models.CharField(max_length=120, blank=True,
                                       help_text="host:port for network printers.")
    label_width_mm = models.DecimalField(max_digits=6, decimal_places=2, default=50)
    label_height_mm = models.DecimalField(max_digits=6, decimal_places=2, default=25)
    label_gap_mm = models.DecimalField(max_digits=5, decimal_places=2, default=2)
    margin_mm = models.DecimalField(max_digits=5, decimal_places=2, default=1.5)
    columns_per_row = models.PositiveSmallIntegerField(
        default=1, help_text="Labels side by side across the web. 1 for a roll printer.")
    dpi = models.PositiveSmallIntegerField(default=203,
                                           help_text="203 dpi (8 dots/mm) is typical.")
    print_density = models.PositiveSmallIntegerField(default=8,
                                                     help_text="Darkness, 0-15 on most units.")
    print_speed = models.PositiveSmallIntegerField(default=4, help_text="Inches per second.")
    supports_escpos = models.BooleanField(default=False)
    notes = models.CharField(max_length=255, blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_default", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            PrinterSetting.objects.exclude(pk=self.pk).update(is_default=False)

    @classmethod
    def get_default(cls):
        return cls.objects.filter(is_active=True, is_default=True).first() or \
            cls.objects.filter(is_active=True).first()

    @property
    def dots_per_mm(self):
        return self.dpi / 25.4


class LabelTemplate(TimeStampedModel):
    """A label layout. The built-in 50x25 mm design is seeded as default."""
    name = models.CharField(max_length=100, unique=True)
    width_mm = models.DecimalField(max_digits=6, decimal_places=2, default=50)
    height_mm = models.DecimalField(max_digits=6, decimal_places=2, default=25)
    show_qr = models.BooleanField(default=True)
    show_barcode = models.BooleanField(default=True)
    show_item_number = models.BooleanField(default=True)
    show_item_name = models.BooleanField(default=True)
    show_scan_hint = models.BooleanField(default=True)
    scan_hint_text = models.CharField(max_length=60, default="SCAN TO VIEW PRODUCT DETAILS")
    show_location = models.BooleanField(default=False)
    item_name_max_chars = models.PositiveSmallIntegerField(default=42)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_default", "name"]

    def __str__(self):
        return f"{self.name} ({self.width_mm:g} x {self.height_mm:g} mm)"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            LabelTemplate.objects.exclude(pk=self.pk).update(is_default=False)

    @classmethod
    def get_default(cls):
        return cls.objects.filter(is_active=True, is_default=True).first() or \
            cls.objects.filter(is_active=True).first()


class LabelPrintLog(TimeStampedModel):
    """Barcode / label print history (section 12)."""
    item = models.ForeignKey("items.Item", on_delete=models.CASCADE, related_name="print_logs")
    template = models.ForeignKey(LabelTemplate, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="print_logs")
    printer = models.ForeignKey(PrinterSetting, null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="print_logs")
    copies = models.PositiveIntegerField(default=1)
    is_reprint = models.BooleanField(default=False)
    barcode_snapshot = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["item", "-created_at"])]

    def __str__(self):
        return f"{self.item.item_number} x{self.copies}"
