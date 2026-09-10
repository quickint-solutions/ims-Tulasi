from django import forms
from django.forms import inlineformset_factory

from masters.models import ItemCategory, Location, UnitOfMeasure, Warehouse
from .models import CustomFieldDefinition, Item, ItemDocument, ItemImage


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = [
            "item_number", "name", "category", "sub_category", "description",
            "manufacturer", "model_number", "drawing_number", "oem_part_number",
            "alternate_part_number",
            "material", "material_grade", "weight", "weight_unit",
            "length", "width", "height", "dimension_unit",
            "size", "size_unit", "colour", "spare_type", "application", "specification",
            "uom", "minimum_stock", "maximum_stock", "reorder_level",
            "barcode_number", "image", "default_location", "remarks", "is_active",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "specification": forms.Textarea(attrs={"rows": 3}),
            "remarks": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = ItemCategory.objects.filter(
            is_active=True, parent__isnull=True)
        self.fields["sub_category"].queryset = ItemCategory.objects.filter(
            is_active=True, parent__isnull=False).select_related("parent")
        self.fields["uom"].queryset = UnitOfMeasure.objects.filter(is_active=True)
        self.fields["default_location"].queryset = Location.objects.filter(
            is_active=True).select_related("warehouse")
        self.fields["barcode_number"].required = False
        self.fields["barcode_number"].help_text = (
            "Leave blank to use the item number as the barcode.")
        self.fields["item_number"].widget.attrs.update({"autofocus": True,
                                                        "placeholder": "e.g. SP-001"})

        # Custom fields defined by the administrator
        self.custom_defs = list(CustomFieldDefinition.objects.filter(is_active=True))
        current = (self.instance.custom_fields or {}) if self.instance else {}
        for cf in self.custom_defs:
            key = f"cf_{cf.key}"
            common = {"label": cf.label, "required": cf.is_required,
                      "help_text": cf.help_text, "initial": current.get(cf.key)}
            if cf.field_type == CustomFieldDefinition.FieldType.NUMBER:
                self.fields[key] = forms.DecimalField(**common)
            elif cf.field_type == CustomFieldDefinition.FieldType.DATE:
                self.fields[key] = forms.DateField(
                    widget=forms.DateInput(attrs={"type": "date"}), **common)
            elif cf.field_type == CustomFieldDefinition.FieldType.BOOLEAN:
                common["required"] = False
                self.fields[key] = forms.BooleanField(**common)
            elif cf.field_type == CustomFieldDefinition.FieldType.CHOICE:
                self.fields[key] = forms.ChoiceField(
                    choices=[("", "---------")] + [(c, c) for c in cf.choice_list], **common)
            else:
                self.fields[key] = forms.CharField(max_length=255, **common)

    def clean_item_number(self):
        value = (self.cleaned_data["item_number"] or "").strip().upper()
        qs = Item.objects.filter(item_number=value)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(
                f"Item number {value} already exists. Item numbers must be unique.")
        return value

    def clean_barcode_number(self):
        value = (self.cleaned_data.get("barcode_number") or "").strip().upper()
        if not value:
            return value
        qs = Item.objects.filter(barcode_number=value)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"Barcode {value} is already assigned to another item.")
        return value

    def clean(self):
        data = super().clean()
        sub, cat = data.get("sub_category"), data.get("category")
        if sub and cat and sub.parent_id != cat.pk:
            self.add_error("sub_category",
                           f"'{sub.name}' is not a sub-category of '{cat.name}'.")
        mn, mx = data.get("minimum_stock"), data.get("maximum_stock")
        if mn is not None and mx and mx > 0 and mn > mx:
            self.add_error("maximum_stock",
                           "Maximum stock must be greater than or equal to minimum stock.")
        return data

    def save(self, commit=True):
        item = super().save(commit=False)
        values = dict(item.custom_fields or {})
        for cf in getattr(self, "custom_defs", []):
            val = self.cleaned_data.get(f"cf_{cf.key}")
            values[cf.key] = str(val) if val not in (None, "") else ""
        item.custom_fields = values
        if commit:
            item.save()
            self.save_m2m()
        return item


ItemImageFormSet = inlineformset_factory(
    Item, ItemImage, fields=["image", "caption", "sort_order"], extra=2, can_delete=True)

ItemDocumentFormSet = inlineformset_factory(
    Item, ItemDocument, fields=["file", "doc_type", "title", "is_public"],
    extra=2, can_delete=True)


class CustomFieldForm(forms.ModelForm):
    class Meta:
        model = CustomFieldDefinition
        fields = ["key", "label", "field_type", "choices", "help_text", "is_required",
                  "show_on_public_page", "sort_order", "is_active"]


class ItemImportForm(forms.Form):
    file = forms.FileField(
        label="Excel or CSV file",
        help_text="Columns: Item Number, Item Name, Category, Sub Category, Make, Model, "
                  "Material, Weight, Weight Unit, Size, Size Unit, Colour, UOM, "
                  "Minimum Stock, Maximum Stock, Reorder Level, Barcode, Remarks, "
                  "Warehouse, Rack, Column, Table, Opening Quantity.")
    create_missing_categories = forms.BooleanField(
        initial=True, required=False, label="Create categories that do not exist")
    create_missing_locations = forms.BooleanField(
        initial=True, required=False, label="Create warehouse locations that do not exist")
    update_existing = forms.BooleanField(
        initial=False, required=False,
        label="Update items that already exist (otherwise they are skipped)")
    opening_document_number = forms.CharField(
        required=False, max_length=64,
        help_text="If opening quantities are present, they are posted under this "
                  "document number. Leave blank to skip opening stock.")
    opening_warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.filter(is_active=True), required=False,
        help_text="Fallback warehouse when the sheet does not name one.")
