from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey("accounts.User", null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    updated_by = models.ForeignKey("accounts.User", null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta:
        abstract = True


class UnitOfMeasure(TimeStampedModel):
    code = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=64)
    decimal_places = models.PositiveSmallIntegerField(
        default=0, help_text="0 for whole units such as NOS; 2-3 for KG, MTR, LTR.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Unit of Measure"
        verbose_name_plural = "Units of Measure"

    def __str__(self):
        return self.code


class ItemCategory(TimeStampedModel):
    """Mandatory item category with optional sub-categories (section 4)."""
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=32, unique=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                               related_name="children")
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["parent__name", "name"]
        verbose_name = "Item Category"
        verbose_name_plural = "Item Categories"
        constraints = [
            models.UniqueConstraint(fields=["parent", "name"], name="uniq_category_name_per_parent")
        ]

    def __str__(self):
        return f"{self.parent.name} / {self.name}" if self.parent_id else self.name

    @property
    def is_subcategory(self):
        return self.parent_id is not None

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = slugify(self.name).upper().replace("-", "_")[:32]
        super().save(*args, **kwargs)

    def clean(self):
        node, seen = self.parent, {self.pk}
        while node is not None:
            if node.pk in seen:
                raise ValidationError({"parent": "Category hierarchy cannot contain a loop."})
            seen.add(node.pk)
            node = node.parent


class Warehouse(TimeStampedModel):
    """A physically independent stock-holding site (section 5)."""
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=120, unique=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=64, blank=True)
    contact_person = models.CharField(max_length=100, blank=True)
    contact_number = models.CharField(max_length=20, blank=True)
    remarks = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Rack(TimeStampedModel):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="racks")
    code = models.CharField(max_length=32, help_text="Rack number or name, e.g. RACK-A")
    name = models.CharField(max_length=100, blank=True)
    description = models.CharField(max_length=255, blank=True)
    remarks = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["warehouse__name", "code"]
        constraints = [
            models.UniqueConstraint(fields=["warehouse", "code"], name="uniq_rack_per_warehouse")
        ]

    def __str__(self):
        return f"{self.warehouse.code} / {self.code}"


class RackColumn(TimeStampedModel):
    rack = models.ForeignKey(Rack, on_delete=models.PROTECT, related_name="columns")
    code = models.CharField(max_length=32, help_text="Column number or name, e.g. C-01")
    name = models.CharField(max_length=100, blank=True)
    description = models.CharField(max_length=255, blank=True)
    remarks = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "columns"
        ordering = ["rack__code", "code"]
        verbose_name = "Column"
        verbose_name_plural = "Columns"
        constraints = [
            models.UniqueConstraint(fields=["rack", "code"], name="uniq_column_per_rack")
        ]

    def __str__(self):
        return f"{self.rack} / {self.code}"

    @property
    def warehouse(self):
        return self.rack.warehouse


class RackTable(TimeStampedModel):
    column = models.ForeignKey(RackColumn, on_delete=models.PROTECT, related_name="tables")
    code = models.CharField(max_length=32, help_text="Table number or name, e.g. T-03")
    name = models.CharField(max_length=100, blank=True)
    description = models.CharField(max_length=255, blank=True)
    remarks = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "tables"
        ordering = ["column__code", "code"]
        verbose_name = "Table"
        verbose_name_plural = "Tables"
        constraints = [
            models.UniqueConstraint(fields=["column", "code"], name="uniq_table_per_column")
        ]

    def __str__(self):
        return f"{self.column} / {self.code}"

    @property
    def warehouse(self):
        return self.column.rack.warehouse


class LocationQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def for_warehouse(self, warehouse):
        return self.filter(warehouse=warehouse)


class Location(TimeStampedModel):
    """The addressable bin: Warehouse / Rack / Column / Table (section 6).

    Rack, column and table are optional so a warehouse can hold loose or
    floor stock before the rack structure is built out.
    """
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="locations")
    rack = models.ForeignKey(Rack, null=True, blank=True, on_delete=models.PROTECT,
                             related_name="locations")
    column = models.ForeignKey(RackColumn, null=True, blank=True, on_delete=models.PROTECT,
                               related_name="locations")
    table = models.ForeignKey(RackTable, null=True, blank=True, on_delete=models.PROTECT,
                              related_name="locations")
    code = models.CharField(max_length=120, db_index=True,
                            help_text="Full location code, e.g. MAIN/RACK-A/C-01/T-03")
    description = models.CharField(max_length=255, blank=True)
    remarks = models.CharField(max_length=255, blank=True)
    is_default = models.BooleanField(
        default=False, help_text="Fallback bin for this warehouse when none is chosen.")
    is_active = models.BooleanField(default=True)

    objects = LocationQuerySet.as_manager()

    class Meta:
        ordering = ["warehouse__name", "code"]
        indexes = [models.Index(fields=["warehouse", "is_active"])]
        constraints = [
            models.UniqueConstraint(fields=["warehouse", "code"],
                                    name="uniq_location_code_per_warehouse"),
            models.UniqueConstraint(fields=["warehouse", "rack", "column", "table"],
                                    name="uniq_location_path"),
        ]

    def __str__(self):
        return self.code

    def build_code(self):
        parts = [self.warehouse.code if self.warehouse_id else ""]
        for node in (self.rack, self.column, self.table):
            if node is not None:
                parts.append(node.code)
        return "/".join(p for p in parts if p)

    def clean(self):
        errors = {}
        if self.rack_id and self.rack.warehouse_id != self.warehouse_id:
            errors["rack"] = "Rack does not belong to the selected warehouse."
        if self.column_id:
            if not self.rack_id:
                errors["rack"] = "Select a rack before selecting a column."
            elif self.column.rack_id != self.rack_id:
                errors["column"] = "Column does not belong to the selected rack."
        if self.table_id:
            if not self.column_id:
                errors["column"] = "Select a column before selecting a table."
            elif self.table.column_id != self.column_id:
                errors["table"] = "Table does not belong to the selected column."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self.build_code()
        super().save(*args, **kwargs)
        if self.is_default:
            Location.objects.filter(warehouse=self.warehouse, is_default=True).exclude(
                pk=self.pk).update(is_default=False)

    @property
    def rack_code(self):
        return self.rack.code if self.rack_id else ""

    @property
    def column_code(self):
        return self.column.code if self.column_id else ""

    @property
    def table_code(self):
        return self.table.code if self.table_id else ""

    @property
    def display_path(self):
        bits = [self.warehouse.name]
        if self.rack_id:
            bits.append(f"Rack {self.rack.code}")
        if self.column_id:
            bits.append(f"Column {self.column.code}")
        if self.table_id:
            bits.append(f"Table {self.table.code}")
        return " / ".join(bits)
