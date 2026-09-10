from django import forms

from .models import CompanySettings, SystemSettings


class CompanySettingsForm(forms.ModelForm):
    class Meta:
        model = CompanySettings
        fields = ["company_name", "short_name", "logo", "address", "city", "state",
                  "pincode", "country", "contact_number", "email", "website"]
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}


class SystemSettingsForm(forms.ModelForm):
    class Meta:
        model = SystemSettings
        fields = ["allow_negative_stock", "suggest_document_numbers",
                  "inward_prefix", "outward_prefix", "transfer_prefix",
                  "adjustment_prefix", "opening_prefix",
                  "require_adjustment_approval", "scanner_auto_focus", "scanner_beep",
                  "public_page_enabled", "show_public_stock", "show_public_location",
                  "low_stock_banner", "date_format", "rows_per_page"]


class BackupForm(forms.Form):
    include_media = forms.BooleanField(
        initial=True, required=False,
        label="Include product images and documents",
        help_text="Turn this off for a much smaller, data-only backup.")
    notes = forms.CharField(max_length=255, required=False)


class RestoreForm(forms.Form):
    file = forms.FileField(label="Backup file (.zip)")
    restore_media = forms.BooleanField(initial=True, required=False,
                                       label="Also restore images and documents")
    confirm = forms.BooleanField(
        label="I understand this replaces all current data",
        error_messages={"required": "Tick the confirmation box to restore."})
