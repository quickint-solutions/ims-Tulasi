from django import forms

from api.models import ApiKey
from .models import ErpNextSettings


class ErpNextSettingsForm(forms.ModelForm):
    api_secret = forms.CharField(widget=forms.PasswordInput(render_value=True),
                                 required=False,
                                 help_text="Stored server-side; never exposed to the browser "
                                           "in plain text once saved.")

    class Meta:
        model = ErpNextSettings
        fields = ["is_enabled", "base_url", "api_key", "api_secret", "company",
                  "default_warehouse", "sync_mode", "sync_items", "sync_categories",
                  "sync_warehouses", "sync_stock", "sync_inward", "sync_outward",
                  "sync_transfer", "verify_ssl", "timeout_seconds"]

    def clean(self):
        data = super().clean()
        if data.get("is_enabled"):
            for field in ("base_url", "api_key", "company"):
                if not data.get(field):
                    self.add_error(field, "Required when the integration is enabled.")
            if not data.get("api_secret") and not self.instance.api_secret:
                self.add_error("api_secret", "Required when the integration is enabled.")
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        if not self.cleaned_data.get("api_secret"):
            obj.api_secret = self.instance.api_secret
        if commit:
            obj.save()
        return obj


class ApiKeyForm(forms.ModelForm):
    can_write = forms.BooleanField(
        required=False, label="Allow write operations",
        help_text="Off means the key can read only. Writes are still limited by the "
                  "linked user's role permissions.")

    class Meta:
        model = ApiKey
        fields = ["name", "user", "allowed_ips", "rate_limit", "expires_at", "is_active"]
        widgets = {"expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}
