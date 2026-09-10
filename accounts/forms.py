from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import AppPermission, Role, User


class LoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(
        attrs={"autofocus": True, "autocomplete": "username", "placeholder": "Username"}))
    password = forms.CharField(widget=forms.PasswordInput(
        attrs={"autocomplete": "current-password", "placeholder": "Password"}))


class UserForm(forms.ModelForm):
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput, required=False,
                                help_text="Leave blank to keep the current password.")
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput,
                                required=False)

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "employee_code", "phone",
                  "role", "default_warehouse", "allowed_warehouses",
                  "extra_permissions", "denied_permissions",
                  "is_active", "must_change_password"]
        widgets = {
            "allowed_warehouses": forms.CheckboxSelectMultiple,
            "extra_permissions": forms.SelectMultiple(attrs={"size": 8}),
            "denied_permissions": forms.SelectMultiple(attrs={"size": 8}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].queryset = Role.objects.filter(is_active=True)
        if self.instance.pk is None:
            self.fields["password1"].required = True
            self.fields["password2"].required = True
            self.fields["password1"].help_text = "Minimum 8 characters."

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 or p2:
            if p1 != p2:
                self.add_error("password2", "The two password fields do not match.")
            elif len(p1) < 8:
                self.add_error("password1", "Password must be at least 8 characters.")
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        pwd = self.cleaned_data.get("password1")
        if pwd:
            user.set_password(pwd)
        if commit:
            user.save()
            self.save_m2m()
        return user


class RoleForm(forms.ModelForm):
    class Meta:
        model = Role
        fields = ["code", "name", "description", "permissions", "is_active"]
        widgets = {"permissions": forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.is_system:
            self.fields["code"].disabled = True

    @property
    def grouped_permissions(self):
        """[(group, [bound checkbox subwidgets]), ...] for a tidy template."""
        field = self["permissions"]
        by_group = {}
        for sub in field:
            perm = AppPermission.objects.filter(pk=sub.data["value"].value).first()
            by_group.setdefault(perm.group if perm else "Other", []).append(sub)
        return list(by_group.items())


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone", "default_warehouse"]
