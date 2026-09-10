from django import forms

from items.models import Item
from masters.models import ItemCategory, Warehouse
from .models import LabelTemplate, PrinterSetting


class PrinterSettingForm(forms.ModelForm):
    class Meta:
        model = PrinterSetting
        fields = ["name", "printer_type", "connection_type", "system_printer_name",
                  "network_address", "label_width_mm", "label_height_mm", "label_gap_mm",
                  "margin_mm", "columns_per_row", "dpi", "print_density", "print_speed",
                  "supports_escpos", "notes", "is_default", "is_active"]


class LabelTemplateForm(forms.ModelForm):
    class Meta:
        model = LabelTemplate
        fields = ["name", "width_mm", "height_mm", "show_qr", "show_barcode",
                  "show_item_number", "show_item_name", "show_scan_hint", "scan_hint_text",
                  "show_location", "item_name_max_chars", "is_default", "is_active"]


class LabelPreviewForm(forms.Form):
    """Live 50 x 25 mm preview (section 17)."""
    item = forms.ModelChoiceField(
        queryset=Item.objects.filter(is_active=True).select_related("uom"),
        label="Item")
    template = forms.ModelChoiceField(queryset=LabelTemplate.objects.filter(is_active=True),
                                      required=False, label="Label size / template")
    printer = forms.ModelChoiceField(queryset=PrinterSetting.objects.filter(is_active=True),
                                     required=False, label="Printer")
    copies = forms.IntegerField(min_value=1, max_value=500, initial=1, label="Label quantity")
    zoom = forms.ChoiceField(choices=[("1", "100% (actual size)"), ("2", "200%"),
                                      ("3", "300%"), ("4", "400%")],
                             initial="3", required=False, label="Preview zoom")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["template"].empty_label = "Default 50 x 25 mm"
        self.fields["printer"].empty_label = "Browser print dialog"


class BatchPrintForm(forms.Form):
    """Select many items and print a sheet or roll of labels."""
    SELECTION = [("selected", "Chosen items"), ("category", "Whole category"),
                 ("warehouse", "Everything stocked in a warehouse"),
                 ("all", "Every active item")]

    mode = forms.ChoiceField(choices=SELECTION, initial="selected", label="Print labels for")
    items = forms.ModelMultipleChoiceField(
        queryset=Item.objects.filter(is_active=True), required=False,
        widget=forms.SelectMultiple(attrs={"size": 12}))
    category = forms.ModelChoiceField(queryset=ItemCategory.objects.filter(is_active=True),
                                      required=False)
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True),
                                       required=False)
    copies = forms.IntegerField(min_value=1, max_value=50, initial=1,
                                label="Copies of each label")
    template = forms.ModelChoiceField(queryset=LabelTemplate.objects.filter(is_active=True),
                                      required=False)
    printer = forms.ModelChoiceField(queryset=PrinterSetting.objects.filter(is_active=True),
                                     required=False)

    def clean(self):
        data = super().clean()
        mode = data.get("mode")
        if mode == "selected" and not data.get("items"):
            self.add_error("items", "Choose at least one item.")
        if mode == "category" and not data.get("category"):
            self.add_error("category", "Choose a category.")
        if mode == "warehouse" and not data.get("warehouse"):
            self.add_error("warehouse", "Choose a warehouse.")
        return data

    def resolve_items(self):
        data = self.cleaned_data
        mode = data["mode"]
        if mode == "selected":
            return data["items"]
        if mode == "category":
            cat = data["category"]
            return Item.objects.filter(is_active=True).filter(
                models_q_category(cat)).order_by("item_number")
        if mode == "warehouse":
            return (Item.objects.filter(is_active=True,
                                        stock_balances__warehouse=data["warehouse"],
                                        stock_balances__quantity__gt=0)
                    .distinct().order_by("item_number"))
        return Item.objects.filter(is_active=True).order_by("item_number")


def models_q_category(cat):
    from django.db.models import Q
    return Q(category=cat) | Q(sub_category=cat)
