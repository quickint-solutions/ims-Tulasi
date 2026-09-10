from django import forms

from .models import (ItemCategory, Location, Rack, RackColumn, RackTable,
                     UnitOfMeasure, Warehouse)


class ItemCategoryForm(forms.ModelForm):
    class Meta:
        model = ItemCategory
        fields = ["name", "code", "parent", "description", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].required = False
        self.fields["code"].help_text = "Auto-generated from the name if left blank."
        qs = ItemCategory.objects.filter(parent__isnull=True, is_active=True)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        self.fields["parent"].queryset = qs
        self.fields["parent"].label = "Parent category (leave blank for a top-level category)"


class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ["code", "name", "address", "city", "contact_person", "contact_number",
                  "remarks", "is_active"]


class RackForm(forms.ModelForm):
    class Meta:
        model = Rack
        fields = ["warehouse", "code", "name", "description", "remarks", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warehouse"].queryset = Warehouse.objects.filter(is_active=True)


class RackColumnForm(forms.ModelForm):
    class Meta:
        model = RackColumn
        fields = ["rack", "code", "name", "description", "remarks", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["rack"].queryset = Rack.objects.filter(is_active=True).select_related("warehouse")


class RackTableForm(forms.ModelForm):
    class Meta:
        model = RackTable
        fields = ["column", "code", "name", "description", "remarks", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["column"].queryset = RackColumn.objects.filter(
            is_active=True).select_related("rack__warehouse")


class LocationForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ["warehouse", "rack", "column", "table", "code", "description",
                  "remarks", "is_default", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].required = False
        self.fields["code"].help_text = ("Built automatically as "
                                         "WAREHOUSE/RACK/COLUMN/TABLE if left blank.")
        self.fields["warehouse"].queryset = Warehouse.objects.filter(is_active=True)
        self.fields["warehouse"].widget.attrs["data-chain"] = "warehouse"
        self.fields["rack"].widget.attrs["data-chain"] = "rack"
        self.fields["column"].widget.attrs["data-chain"] = "column"
        self.fields["table"].widget.attrs["data-chain"] = "table"
        # Narrow the dependent querysets to what is actually selectable.
        wh = self.data.get("warehouse") or getattr(self.instance, "warehouse_id", None)
        rack = self.data.get("rack") or getattr(self.instance, "rack_id", None)
        col = self.data.get("column") or getattr(self.instance, "column_id", None)
        self.fields["rack"].queryset = (Rack.objects.filter(warehouse_id=wh, is_active=True)
                                        if wh else Rack.objects.none())
        self.fields["column"].queryset = (RackColumn.objects.filter(rack_id=rack, is_active=True)
                                          if rack else RackColumn.objects.none())
        self.fields["table"].queryset = (RackTable.objects.filter(column_id=col, is_active=True)
                                         if col else RackTable.objects.none())


class UnitOfMeasureForm(forms.ModelForm):
    class Meta:
        model = UnitOfMeasure
        fields = ["code", "name", "decimal_places", "is_active"]


class BulkLocationForm(forms.Form):
    """Generate a rack/column/table grid in one step."""
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True))
    rack_codes = forms.CharField(
        label="Rack codes", help_text="Comma separated, e.g. RACK-A, RACK-B, RACK-C")
    columns_per_rack = forms.IntegerField(min_value=0, max_value=200, initial=4,
                                          help_text="Numbered C-01, C-02, ... Use 0 to skip.")
    tables_per_column = forms.IntegerField(min_value=0, max_value=200, initial=4,
                                           help_text="Numbered T-01, T-02, ... Use 0 to skip.")
    create_locations = forms.BooleanField(
        initial=True, required=False,
        label="Also create a Location record for every table")

    def clean_rack_codes(self):
        codes = [c.strip().upper() for c in self.cleaned_data["rack_codes"].split(",") if c.strip()]
        if not codes:
            raise forms.ValidationError("Enter at least one rack code.")
        if len(codes) > 100:
            raise forms.ValidationError("Create at most 100 racks at a time.")
        return codes
