"""Stock engine - QUANTITY ONLY.

No price, rate, cost, amount, tax or currency field exists in this module.
Current Stock = Opening + Inward - Outward +/- Adjustment +/- Transfer (section 7).

Stock is never trusted from an editable number (section 49): every change is
posted through stock.services and writes an immutable StockMovement row, with
StockBalance maintained as a derived, reconcilable cache.
"""
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from core.validators import validate_document_file
from masters.models import TimeStampedModel

ZERO = Decimal("0")


def attachment_path(instance, filename):
    return f"documents/{instance.__class__.__name__.lower()}/{instance.document_number}/{filename}"


class MovementType(models.TextChoices):
    OPENING = "OPENING", "Opening Stock"
    INWARD = "INWARD", "Inward"
    OUTWARD = "OUTWARD", "Outward"
    TRANSFER_IN = "TRANSFER_IN", "Transfer In"
    TRANSFER_OUT = "TRANSFER_OUT", "Transfer Out"
    ADJUSTMENT = "ADJUSTMENT", "Adjustment"
    RETURN = "RETURN", "Return"
    CORRECTION = "CORRECTION", "Correction"


class DocumentStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    POSTED = "POSTED", "Posted"
    CANCELLED = "CANCELLED", "Cancelled"


# --------------------------------------------------------------------------
# Balances
# --------------------------------------------------------------------------
class StockBalanceQuerySet(models.QuerySet):
    def in_stock(self):
        return self.filter(quantity__gt=0)


class StockBalance(models.Model):
    """Quantity of one item at one physical location (section 45)."""
    item = models.ForeignKey("items.Item", on_delete=models.PROTECT, related_name="stock_balances")
    location = models.ForeignKey("masters.Location", on_delete=models.PROTECT,
                                 related_name="stock_balances")
    warehouse = models.ForeignKey("masters.Warehouse", on_delete=models.PROTECT,
                                  related_name="stock_balances")
    quantity = models.DecimalField(max_digits=18, decimal_places=3, default=ZERO)
    reserved_quantity = models.DecimalField(max_digits=18, decimal_places=3, default=ZERO,
                                            validators=[MinValueValidator(0)])
    last_movement_at = models.DateTimeField(null=True, blank=True)

    objects = StockBalanceQuerySet.as_manager()

    class Meta:
        ordering = ["item__item_number", "warehouse__name", "location__code"]
        constraints = [
            models.UniqueConstraint(fields=["item", "location"], name="uniq_balance_item_location")
        ]
        indexes = [
            models.Index(fields=["item", "warehouse"]),
            models.Index(fields=["warehouse", "location"]),
        ]

    def __str__(self):
        return f"{self.item.item_number} @ {self.location.code} = {self.quantity:g}"

    @property
    def available_quantity(self):
        return self.quantity - self.reserved_quantity

    @classmethod
    def total_for_item(cls, item, warehouse=None):
        qs = cls.objects.filter(item=item)
        if warehouse is not None:
            qs = qs.filter(warehouse=warehouse)
        return qs.aggregate(t=models.Sum("quantity"))["t"] or ZERO

    @classmethod
    def available_for_item(cls, item, warehouse=None):
        qs = cls.objects.filter(item=item)
        if warehouse is not None:
            qs = qs.filter(warehouse=warehouse)
        agg = qs.aggregate(q=models.Sum("quantity"), r=models.Sum("reserved_quantity"))
        return (agg["q"] or ZERO) - (agg["r"] or ZERO)

    @classmethod
    def available_at(cls, item, location):
        row = cls.objects.filter(item=item, location=location).first()
        return row.available_quantity if row else ZERO


# --------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------
class StockMovementQuerySet(models.QuerySet):
    def inward_like(self):
        return self.filter(direction=1)

    def outward_like(self):
        return self.filter(direction=-1)

    def between(self, date_from, date_to):
        qs = self
        if date_from:
            qs = qs.filter(movement_date__gte=date_from)
        if date_to:
            qs = qs.filter(movement_date__lte=date_to)
        return qs


class StockMovement(models.Model):
    """Immutable stock ledger row (section 22). Never deleted - reverse instead."""
    movement_date = models.DateField(db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    movement_type = models.CharField(max_length=20, choices=MovementType.choices, db_index=True)
    direction = models.SmallIntegerField(help_text="+1 increases stock, -1 decreases stock.")

    item = models.ForeignKey("items.Item", on_delete=models.PROTECT, related_name="movements")
    warehouse = models.ForeignKey("masters.Warehouse", on_delete=models.PROTECT,
                                  related_name="movements")
    location = models.ForeignKey("masters.Location", on_delete=models.PROTECT,
                                 related_name="movements")
    quantity = models.DecimalField(max_digits=18, decimal_places=3,
                                   validators=[MinValueValidator(Decimal("0.001"))],
                                   help_text="Always positive; direction carries the sign.")
    balance_after = models.DecimalField(max_digits=18, decimal_places=3, default=ZERO,
                                        help_text="Item/location balance immediately after this row.")

    document_type = models.CharField(max_length=20, blank=True, db_index=True)
    document_number = models.CharField(max_length=64, blank=True, db_index=True)
    document_id = models.PositiveIntegerField(null=True, blank=True)
    line_id = models.PositiveIntegerField(null=True, blank=True)

    reference = models.CharField(max_length=120, blank=True)
    party = models.CharField(max_length=150, blank=True,
                             help_text="Supplier, department, customer or destination.")
    remarks = models.CharField(max_length=255, blank=True)

    user = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="movements")
    is_reversal = models.BooleanField(default=False)
    reverses = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="reversed_by")

    objects = StockMovementQuerySet.as_manager()

    class Meta:
        ordering = ["-movement_date", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["item", "-movement_date"]),
            models.Index(fields=["warehouse", "-movement_date"]),
            models.Index(fields=["movement_type", "-movement_date"]),
            models.Index(fields=["document_type", "document_number"]),
        ]

    def __str__(self):
        sign = "+" if self.direction > 0 else "-"
        return f"{self.movement_date} {self.item_id} {sign}{self.quantity:g}"

    @property
    def signed_quantity(self):
        return self.quantity * self.direction

    def delete(self, *args, **kwargs):  # pragma: no cover - guarded by design
        raise RuntimeError(
            "Stock movements are immutable. Post a reversal or correction instead.")


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------
class StockDocument(TimeStampedModel):
    """Shared header for inward / outward / transfer / adjustment / opening.

    Document numbers are ALWAYS manually entered (section 35). The UI may
    suggest a next number, but the user can overwrite it.
    """
    document_number = models.CharField(max_length=64, db_index=True)
    document_date = models.DateField(default=timezone.localdate, db_index=True)
    reference_number = models.CharField(max_length=64, blank=True)
    remarks = models.TextField(blank=True)
    attachment = models.FileField(upload_to=attachment_path, blank=True, null=True,
                                  validators=[validate_document_file])
    status = models.CharField(max_length=10, choices=DocumentStatus.choices,
                              default=DocumentStatus.DRAFT, db_index=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.ForeignKey("accounts.User", null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="+")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey("accounts.User", null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")
    cancel_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        abstract = True
        ordering = ["-document_date", "-id"]

    def __str__(self):
        return self.document_number

    @property
    def is_posted(self):
        return self.status == DocumentStatus.POSTED

    @property
    def is_editable(self):
        return self.status == DocumentStatus.DRAFT

    def save(self, *args, **kwargs):
        self.document_number = self.document_number.strip().upper()
        super().save(*args, **kwargs)


class InwardDocument(StockDocument):
    warehouse = models.ForeignKey("masters.Warehouse", on_delete=models.PROTECT,
                                  related_name="inward_documents")
    supplier = models.CharField("Supplier / source", max_length=150, blank=True)

    class Meta(StockDocument.Meta):
        abstract = False
        ordering = ["-document_date", "-id"]
        constraints = [models.UniqueConstraint(fields=["document_number"],
                                               name="uniq_inward_document_number")]

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("stock:inward_detail", args=[self.pk])

    @property
    def total_quantity(self):
        return self.lines.aggregate(t=models.Sum("quantity"))["t"] or ZERO


class InwardItem(models.Model):
    document = models.ForeignKey(InwardDocument, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey("items.Item", on_delete=models.PROTECT, related_name="inward_lines")
    location = models.ForeignKey("masters.Location", on_delete=models.PROTECT,
                                 related_name="inward_lines")
    quantity = models.DecimalField(max_digits=18, decimal_places=3,
                                   validators=[MinValueValidator(Decimal("0.001"))])
    remarks = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.item.item_number} +{self.quantity:g}"


class OutwardDocument(StockDocument):
    warehouse = models.ForeignKey("masters.Warehouse", on_delete=models.PROTECT,
                                  related_name="outward_documents")
    destination = models.CharField("Destination / customer / department", max_length=150,
                                   blank=True)
    issued_to = models.CharField(max_length=150, blank=True)
    allow_negative = models.BooleanField(
        default=False,
        help_text="Admin override: post even if it takes a bin below zero (section 9).")

    class Meta(StockDocument.Meta):
        abstract = False
        ordering = ["-document_date", "-id"]
        constraints = [models.UniqueConstraint(fields=["document_number"],
                                               name="uniq_outward_document_number")]

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("stock:outward_detail", args=[self.pk])

    @property
    def total_quantity(self):
        return self.lines.aggregate(t=models.Sum("quantity"))["t"] or ZERO


class OutwardItem(models.Model):
    document = models.ForeignKey(OutwardDocument, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey("items.Item", on_delete=models.PROTECT, related_name="outward_lines")
    location = models.ForeignKey("masters.Location", on_delete=models.PROTECT,
                                 related_name="outward_lines")
    quantity = models.DecimalField(max_digits=18, decimal_places=3,
                                   validators=[MinValueValidator(Decimal("0.001"))])
    remarks = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.item.item_number} -{self.quantity:g}"


class TransferDocument(StockDocument):
    """Warehouse-to-warehouse or bin-to-bin movement (section 10)."""
    from_warehouse = models.ForeignKey("masters.Warehouse", on_delete=models.PROTECT,
                                       related_name="transfers_out")
    to_warehouse = models.ForeignKey("masters.Warehouse", on_delete=models.PROTECT,
                                     related_name="transfers_in")
    allow_negative = models.BooleanField(default=False)

    class Meta(StockDocument.Meta):
        abstract = False
        ordering = ["-document_date", "-id"]
        constraints = [models.UniqueConstraint(fields=["document_number"],
                                               name="uniq_transfer_document_number")]

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("stock:transfer_detail", args=[self.pk])

    @property
    def total_quantity(self):
        return self.lines.aggregate(t=models.Sum("quantity"))["t"] or ZERO


class TransferItem(models.Model):
    document = models.ForeignKey(TransferDocument, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey("items.Item", on_delete=models.PROTECT, related_name="transfer_lines")
    from_location = models.ForeignKey("masters.Location", on_delete=models.PROTECT,
                                      related_name="transfer_out_lines")
    to_location = models.ForeignKey("masters.Location", on_delete=models.PROTECT,
                                    related_name="transfer_in_lines")
    quantity = models.DecimalField(max_digits=18, decimal_places=3,
                                   validators=[MinValueValidator(Decimal("0.001"))])
    remarks = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.item.item_number} {self.quantity:g}"


class AdjustmentDocument(StockDocument):
    """Physical stock verification (section 11)."""

    class Reason(models.TextChoices):
        PHYSICAL_COUNT = "PHYSICAL_COUNT", "Physical count difference"
        DAMAGE = "DAMAGE", "Damaged / scrapped"
        FOUND = "FOUND", "Found stock"
        SHORTAGE = "SHORTAGE", "Shortage"
        DATA_ENTRY = "DATA_ENTRY", "Data entry correction"
        OTHER = "OTHER", "Other"

    warehouse = models.ForeignKey("masters.Warehouse", on_delete=models.PROTECT,
                                  related_name="adjustments")
    reason = models.CharField(max_length=20, choices=Reason.choices,
                              default=Reason.PHYSICAL_COUNT)
    approved_by = models.ForeignKey("accounts.User", null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="approved_adjustments")
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta(StockDocument.Meta):
        abstract = False
        ordering = ["-document_date", "-id"]
        constraints = [models.UniqueConstraint(fields=["document_number"],
                                               name="uniq_adjustment_document_number")]

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("stock:adjustment_detail", args=[self.pk])

    @property
    def total_difference(self):
        return sum((line.difference for line in self.lines.all()), ZERO)


class AdjustmentItem(models.Model):
    document = models.ForeignKey(AdjustmentDocument, on_delete=models.CASCADE,
                                 related_name="lines")
    item = models.ForeignKey("items.Item", on_delete=models.PROTECT,
                             related_name="adjustment_lines")
    location = models.ForeignKey("masters.Location", on_delete=models.PROTECT,
                                 related_name="adjustment_lines")
    system_quantity = models.DecimalField(max_digits=18, decimal_places=3, default=ZERO,
                                          help_text="Snapshot of system stock when counted.")
    physical_quantity = models.DecimalField(max_digits=18, decimal_places=3, default=ZERO,
                                            validators=[MinValueValidator(0)])
    reason = models.CharField(max_length=255, blank=True)
    remarks = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.item.item_number} {self.difference:+g}"

    @property
    def difference(self):
        return (self.physical_quantity or ZERO) - (self.system_quantity or ZERO)


class OpeningStockDocument(StockDocument):
    """Manual opening balances (section 34)."""
    warehouse = models.ForeignKey("masters.Warehouse", on_delete=models.PROTECT,
                                  related_name="opening_documents")

    class Meta(StockDocument.Meta):
        abstract = False
        ordering = ["-document_date", "-id"]
        constraints = [models.UniqueConstraint(fields=["document_number"],
                                               name="uniq_opening_document_number")]

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("stock:opening_detail", args=[self.pk])

    @property
    def total_quantity(self):
        return self.lines.aggregate(t=models.Sum("quantity"))["t"] or ZERO


class OpeningStockItem(models.Model):
    document = models.ForeignKey(OpeningStockDocument, on_delete=models.CASCADE,
                                 related_name="lines")
    item = models.ForeignKey("items.Item", on_delete=models.PROTECT, related_name="opening_lines")
    location = models.ForeignKey("masters.Location", on_delete=models.PROTECT,
                                 related_name="opening_lines")
    quantity = models.DecimalField(max_digits=18, decimal_places=3,
                                   validators=[MinValueValidator(Decimal("0.001"))])
    remarks = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.item.item_number} opening {self.quantity:g}"
