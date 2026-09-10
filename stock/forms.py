from django import forms
from django.forms import inlineformset_factory

from core.models import SystemSettings
from core.utils import suggest_document_number
from items.models import Item
from masters.models import Location, Warehouse
from .models import (AdjustmentDocument, AdjustmentItem, InwardDocument, InwardItem,
                     OpeningStockDocument, OpeningStockItem, OutwardDocument, OutwardItem,
                     TransferDocument, TransferItem)


class DocumentFormMixin:
    """Shared behaviour: manual document numbers with an optional suggestion."""
    number_prefix_field = None

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["document_number"].help_text = (
            "Enter any number you like - IN-001, GRN-125, 2026-458. "
            "No yearly numbering is forced.")
        self.fields["document_number"].widget.attrs.update({"autofocus": True})
        self.fields["document_date"].widget = forms.DateInput(
            attrs={"type": "date"}, format="%Y-%m-%d")
        self.fields["document_date"].input_formats = ["%Y-%m-%d"]
        for name in ("warehouse", "from_warehouse", "to_warehouse"):
            if name in self.fields and user is not None:
                self.fields[name].queryset = user.warehouse_queryset()
        if "warehouse" in self.fields:
            self.fields["warehouse"].widget.attrs["data-chain"] = "warehouse"
        if not self.instance.pk and not self.initial.get("document_number"):
            settings_row = SystemSettings.load()
            if settings_row.suggest_document_numbers and self.number_prefix_field:
                prefix = getattr(settings_row, self.number_prefix_field, "")
                self.fields["document_number"].initial = suggest_document_number(
                    self._meta.model, prefix)
        if user is not None and "allow_negative" in self.fields:
            if not user.has_perm_code("stock.negative_override"):
                self.fields["allow_negative"].disabled = True
                self.fields["allow_negative"].help_text = (
                    "Only a user with the negative-stock override permission can set this.")

    def clean_document_number(self):
        value = (self.cleaned_data["document_number"] or "").strip().upper()
        if not value:
            raise forms.ValidationError("Enter a document number.")
        qs = self._meta.model.objects.filter(document_number=value)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(
                f"Document number {value} already exists. Use a different number.")
        return value


class LineFormMixin:
    """Restricts item/location choices and applies the location picker chain."""

    def __init__(self, *args, warehouse=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = Item.objects.filter(is_active=True).select_related("uom")
        for name in ("location", "from_location", "to_location"):
            if name in self.fields:
                qs = Location.objects.filter(is_active=True).select_related("warehouse")
                if warehouse is not None and name != "to_location":
                    qs = qs.filter(warehouse=warehouse)
                self.fields[name].queryset = qs
        if "quantity" in self.fields:
            self.fields["quantity"].widget.attrs.update(
                {"step": "0.001", "min": "0.001", "inputmode": "decimal"})


# ------------------------------------------------------------------ Inward
class InwardForm(DocumentFormMixin, forms.ModelForm):
    number_prefix_field = "inward_prefix"

    class Meta:
        model = InwardDocument
        fields = ["document_number", "document_date", "warehouse", "supplier",
                  "reference_number", "remarks", "attachment"]
        widgets = {"remarks": forms.Textarea(attrs={"rows": 2})}


class InwardLineForm(LineFormMixin, forms.ModelForm):
    class Meta:
        model = InwardItem
        fields = ["item", "location", "quantity", "remarks"]


InwardLineFormSet = inlineformset_factory(InwardDocument, InwardItem, form=InwardLineForm,
                                          extra=1, can_delete=True, min_num=1,
                                          validate_min=True)


# ----------------------------------------------------------------- Outward
class OutwardForm(DocumentFormMixin, forms.ModelForm):
    number_prefix_field = "outward_prefix"

    class Meta:
        model = OutwardDocument
        fields = ["document_number", "document_date", "warehouse", "destination",
                  "issued_to", "reference_number", "remarks", "attachment",
                  "allow_negative"]
        widgets = {"remarks": forms.Textarea(attrs={"rows": 2})}


class OutwardLineForm(LineFormMixin, forms.ModelForm):
    class Meta:
        model = OutwardItem
        fields = ["item", "location", "quantity", "remarks"]


OutwardLineFormSet = inlineformset_factory(OutwardDocument, OutwardItem, form=OutwardLineForm,
                                           extra=1, can_delete=True, min_num=1,
                                           validate_min=True)


# ---------------------------------------------------------------- Transfer
class TransferForm(DocumentFormMixin, forms.ModelForm):
    number_prefix_field = "transfer_prefix"

    class Meta:
        model = TransferDocument
        fields = ["document_number", "document_date", "from_warehouse", "to_warehouse",
                  "reference_number", "remarks", "attachment", "allow_negative"]
        widgets = {"remarks": forms.Textarea(attrs={"rows": 2})}

    def clean(self):
        data = super().clean()
        src, dst = data.get("from_warehouse"), data.get("to_warehouse")
        if src and dst and src == dst:
            # Same-warehouse moves are allowed (rack to rack); flagged only for clarity.
            pass
        return data


class TransferLineForm(LineFormMixin, forms.ModelForm):
    class Meta:
        model = TransferItem
        fields = ["item", "from_location", "to_location", "quantity", "remarks"]

    def clean(self):
        data = super().clean()
        src, dst = data.get("from_location"), data.get("to_location")
        if src and dst and src == dst:
            self.add_error("to_location", "Source and destination location must differ.")
        return data


TransferLineFormSet = inlineformset_factory(TransferDocument, TransferItem,
                                            form=TransferLineForm, extra=1, can_delete=True,
                                            min_num=1, validate_min=True)


# -------------------------------------------------------------- Adjustment
class AdjustmentForm(DocumentFormMixin, forms.ModelForm):
    number_prefix_field = "adjustment_prefix"

    class Meta:
        model = AdjustmentDocument
        fields = ["document_number", "document_date", "warehouse", "reason",
                  "reference_number", "remarks", "attachment"]
        widgets = {"remarks": forms.Textarea(attrs={"rows": 2})}


class AdjustmentLineForm(LineFormMixin, forms.ModelForm):
    class Meta:
        model = AdjustmentItem
        fields = ["item", "location", "system_quantity", "physical_quantity", "reason",
                  "remarks"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["system_quantity"].disabled = True
        self.fields["system_quantity"].required = False
        self.fields["system_quantity"].help_text = "Filled in automatically when posting."
        self.fields["physical_quantity"].widget.attrs.update(
            {"step": "0.001", "min": "0", "inputmode": "decimal"})


AdjustmentLineFormSet = inlineformset_factory(AdjustmentDocument, AdjustmentItem,
                                              form=AdjustmentLineForm, extra=1,
                                              can_delete=True, min_num=1, validate_min=True)


# ----------------------------------------------------------- Opening stock
class OpeningForm(DocumentFormMixin, forms.ModelForm):
    number_prefix_field = "opening_prefix"

    class Meta:
        model = OpeningStockDocument
        fields = ["document_number", "document_date", "warehouse", "reference_number",
                  "remarks", "attachment"]
        widgets = {"remarks": forms.Textarea(attrs={"rows": 2})}


class OpeningLineForm(LineFormMixin, forms.ModelForm):
    class Meta:
        model = OpeningStockItem
        fields = ["item", "location", "quantity", "remarks"]


OpeningLineFormSet = inlineformset_factory(OpeningStockDocument, OpeningStockItem,
                                           form=OpeningLineForm, extra=1, can_delete=True,
                                           min_num=1, validate_min=True)


# ------------------------------------------------------- Scanner quick forms
class QuickMovementForm(forms.Form):
    """One-item inward/outward straight from the scanner screen (section 46)."""
    ACTIONS = [("INWARD", "Inward"), ("OUTWARD", "Outward")]

    action = forms.ChoiceField(choices=ACTIONS, widget=forms.HiddenInput)
    item_id = forms.IntegerField(widget=forms.HiddenInput)
    document_number = forms.CharField(max_length=64, label="Document number")
    location = forms.ModelChoiceField(queryset=Location.objects.filter(is_active=True),
                                      label="Location")
    quantity = forms.DecimalField(min_value=0.001, decimal_places=3, max_digits=18,
                                  widget=forms.NumberInput(
                                      attrs={"step": "0.001", "inputmode": "decimal"}))
    party = forms.CharField(max_length=150, required=False,
                            label="Supplier / destination")
    remarks = forms.CharField(max_length=255, required=False)

    def __init__(self, *args, user=None, item=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user, self.item = user, item
        qs = Location.objects.filter(is_active=True).select_related("warehouse")
        if user is not None:
            qs = qs.filter(warehouse__in=user.warehouse_queryset())
        self.fields["location"].queryset = qs


class QuickTransferForm(forms.Form):
    item_id = forms.IntegerField(widget=forms.HiddenInput)
    document_number = forms.CharField(max_length=64)
    from_location = forms.ModelChoiceField(queryset=Location.objects.filter(is_active=True))
    to_location = forms.ModelChoiceField(queryset=Location.objects.filter(is_active=True))
    quantity = forms.DecimalField(min_value=0.001, decimal_places=3, max_digits=18,
                                  widget=forms.NumberInput(attrs={"step": "0.001"}))
    remarks = forms.CharField(max_length=255, required=False)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Location.objects.filter(is_active=True).select_related("warehouse")
        if user is not None:
            qs = qs.filter(warehouse__in=user.warehouse_queryset())
        self.fields["from_location"].queryset = qs
        self.fields["to_location"].queryset = qs

    def clean(self):
        data = super().clean()
        if data.get("from_location") and data.get("from_location") == data.get("to_location"):
            self.add_error("to_location", "Source and destination must differ.")
        return data


class StockFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Search")
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True),
                                       required=False)
    category = forms.CharField(required=False, widget=forms.HiddenInput)
