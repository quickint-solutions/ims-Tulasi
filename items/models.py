import secrets

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.urls import reverse

from core.validators import validate_document_file, validate_image_file
from masters.models import ItemCategory, TimeStampedModel, UnitOfMeasure

ITEM_NUMBER_VALIDATOR = RegexValidator(
    r"^[A-Za-z0-9][A-Za-z0-9._\-/]*$",
    "Use letters, digits, dot, dash, underscore or slash. Must start with a letter or digit.",
)


def item_image_path(instance, filename):
    return f"items/{instance.item.item_number}/images/{filename}"


def item_document_path(instance, filename):
    return f"items/{instance.item.item_number}/documents/{filename}"


def item_primary_image_path(instance, filename):
    return f"items/{instance.item_number}/main/{filename}"


def new_qr_token():
    return secrets.token_urlsafe(16)


class ItemQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def with_stock(self):
        # Named `stock_total` because `total_quantity` is a model property and an
        # annotation cannot be assigned over one.
        return self.annotate(
            stock_total=models.Sum("stock_balances__quantity"),
            reserved_total=models.Sum("stock_balances__reserved_quantity"),
        )


class Item(TimeStampedModel):
    """Item / spare part master (section 3). Quantity-only - no price fields."""

    class SpareType(models.TextChoices):
        MECHANICAL = "MECHANICAL", "Mechanical"
        ELECTRICAL = "ELECTRICAL", "Electrical"
        INSTRUMENTATION = "INSTRUMENTATION", "Instrumentation"
        CONSUMABLE = "CONSUMABLE", "Consumable"
        WEAR_PART = "WEAR_PART", "Wear part"
        ROTABLE = "ROTABLE", "Rotable / repairable"
        TOOL = "TOOL", "Tool"
        FABRICATED = "FABRICATED", "Fabricated"
        OTHER = "OTHER", "Other"

    # --- Identification ---
    item_number = models.CharField(
        max_length=50, unique=True, db_index=True, validators=[ITEM_NUMBER_VALIDATOR],
        help_text="Manually entered part number, e.g. SP-001 or BOILER-FD-001.")
    name = models.CharField(max_length=200, db_index=True)
    category = models.ForeignKey(ItemCategory, on_delete=models.PROTECT, related_name="items")
    sub_category = models.ForeignKey(ItemCategory, null=True, blank=True,
                                     on_delete=models.PROTECT, related_name="sub_items")
    description = models.TextField(blank=True)

    # --- Source and identification numbers ---
    manufacturer = models.CharField("Manufacturer / Make", max_length=150, blank=True, db_index=True)
    model_number = models.CharField(max_length=100, blank=True, db_index=True)
    drawing_number = models.CharField(max_length=100, blank=True, db_index=True)
    oem_part_number = models.CharField(max_length=100, blank=True, db_index=True)
    alternate_part_number = models.CharField(max_length=100, blank=True, db_index=True)

    # --- Physical specification ---
    material = models.CharField(max_length=100, blank=True, db_index=True)
    material_grade = models.CharField(max_length=100, blank=True)
    weight = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True,
                                 validators=[MinValueValidator(0)])
    weight_unit = models.CharField(max_length=16, blank=True, default="KG")
    length = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True,
                                 validators=[MinValueValidator(0)])
    width = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True,
                                validators=[MinValueValidator(0)])
    height = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True,
                                 validators=[MinValueValidator(0)])
    dimension_unit = models.CharField(max_length=16, blank=True, default="MM")
    size = models.CharField(max_length=64, blank=True)
    size_unit = models.CharField(max_length=16, blank=True, default="MM")
    colour = models.CharField(max_length=50, blank=True)
    spare_type = models.CharField(max_length=20, choices=SpareType.choices, blank=True)
    application = models.CharField(max_length=255, blank=True,
                                   help_text="Equipment or system this spare is used on.")
    specification = models.TextField(blank=True)

    # --- Stock control (quantities only) ---
    uom = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="items",
                            verbose_name="Unit of Measurement")
    minimum_stock = models.DecimalField(max_digits=16, decimal_places=3, default=0,
                                        validators=[MinValueValidator(0)])
    maximum_stock = models.DecimalField(max_digits=16, decimal_places=3, default=0,
                                        validators=[MinValueValidator(0)])
    reorder_level = models.DecimalField(max_digits=16, decimal_places=3, default=0,
                                        validators=[MinValueValidator(0)])

    # --- Barcode / QR ---
    barcode_number = models.CharField(
        max_length=64, unique=True, db_index=True,
        help_text="Defaults to the item number. Encoded as Code 128.")
    qr_token = models.CharField(max_length=32, unique=True, default=new_qr_token, editable=False,
                                help_text="Opaque token used in the public QR URL.")

    # --- Files ---
    image = models.ImageField(upload_to=item_primary_image_path, blank=True, null=True,
                              validators=[validate_image_file],
                              help_text="Main product image.")

    # --- Housekeeping ---
    default_location = models.ForeignKey(
        "masters.Location", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="default_items",
        help_text="Suggested bin for inward of this item.")
    custom_fields = models.JSONField(default=dict, blank=True,
                                     help_text="User-defined additional fields.")
    remarks = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    objects = ItemQuerySet.as_manager()

    class Meta:
        ordering = ["item_number"]
        indexes = [
            models.Index(fields=["is_active", "category"]),
            models.Index(fields=["name"]),
        ]

    def __str__(self):
        return f"{self.item_number} - {self.name}"

    def save(self, *args, **kwargs):
        self.item_number = self.item_number.strip().upper()
        if not self.barcode_number:
            self.barcode_number = self.item_number
        self.barcode_number = self.barcode_number.strip().upper()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("items:detail", args=[self.pk])

    @property
    def public_url_path(self):
        return reverse("public_item", args=[self.qr_token])

    def public_url(self, request=None):
        if request is not None:
            return request.build_absolute_uri(self.public_url_path)
        from django.conf import settings
        return settings.PUBLIC_BASE_URL.rstrip("/") + self.public_url_path

    # --- Stock helpers (quantity only) ---
    @property
    def total_quantity(self):
        from stock.models import StockBalance
        return StockBalance.total_for_item(self)

    @property
    def available_quantity(self):
        from stock.models import StockBalance
        return StockBalance.available_for_item(self)

    @property
    def stock_status(self):
        """Quantity-based alerts (section 33)."""
        qty = self.total_quantity
        if qty <= 0:
            return "OUT_OF_STOCK"
        if self.reorder_level and qty <= self.reorder_level:
            return "LOW_STOCK"
        if self.maximum_stock and qty > self.maximum_stock:
            return "OVERSTOCK"
        return "IN_STOCK"

    @property
    def stock_status_label(self):
        return {
            "OUT_OF_STOCK": "Out of stock",
            "LOW_STOCK": "Low stock",
            "OVERSTOCK": "Overstock",
            "IN_STOCK": "In stock",
        }[self.stock_status]

    @property
    def dimensions_display(self):
        vals = [v for v in (self.length, self.width, self.height) if v is not None]
        if not vals:
            return ""
        return " x ".join(f"{v:g}" for v in vals) + f" {self.dimension_unit}"

    @property
    def size_display(self):
        return f"{self.size} {self.size_unit}".strip() if self.size else ""

    @property
    def weight_display(self):
        return f"{self.weight:g} {self.weight_unit}".strip() if self.weight is not None else ""


class ItemImage(TimeStampedModel):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to=item_image_path, validators=[validate_image_file])
    caption = models.CharField(max_length=150, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.item.item_number} image {self.pk}"


class ItemDocument(TimeStampedModel):
    class DocType(models.TextChoices):
        DRAWING = "DRAWING", "Drawing"
        SPECIFICATION = "SPECIFICATION", "Specification"
        DATASHEET = "DATASHEET", "Datasheet"
        MANUAL = "MANUAL", "Manual"
        CERTIFICATE = "CERTIFICATE", "Certificate"
        OTHER = "OTHER", "Other"

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="documents")
    file = models.FileField(upload_to=item_document_path, validators=[validate_document_file])
    doc_type = models.CharField(max_length=20, choices=DocType.choices, default=DocType.OTHER)
    title = models.CharField(max_length=150, blank=True)
    is_public = models.BooleanField(
        default=False, help_text="Visible on the public QR page. Keep internal documents private.")

    class Meta:
        ordering = ["doc_type", "id"]

    def __str__(self):
        return self.title or self.file.name

    @property
    def filename(self):
        return self.file.name.rsplit("/", 1)[-1]


class CustomFieldDefinition(TimeStampedModel):
    """User-defined extra item fields (section 3, 'allow custom fields later')."""

    class FieldType(models.TextChoices):
        TEXT = "TEXT", "Text"
        NUMBER = "NUMBER", "Number"
        DATE = "DATE", "Date"
        BOOLEAN = "BOOLEAN", "Yes / No"
        CHOICE = "CHOICE", "Choice list"

    key = models.SlugField(max_length=50, unique=True)
    label = models.CharField(max_length=100)
    field_type = models.CharField(max_length=10, choices=FieldType.choices,
                                  default=FieldType.TEXT)
    choices = models.TextField(blank=True, help_text="One option per line, for choice lists.")
    help_text = models.CharField(max_length=200, blank=True)
    is_required = models.BooleanField(default=False)
    show_on_public_page = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "label"]

    def __str__(self):
        return self.label

    @property
    def choice_list(self):
        return [c.strip() for c in self.choices.splitlines() if c.strip()]
