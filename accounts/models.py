from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from .permissions_catalog import PERMISSION_LABELS


class AppPermission(models.Model):
    """A single application capability, seeded from permissions_catalog."""
    code = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=128)
    group = models.CharField(max_length=64)

    class Meta:
        ordering = ["group", "code"]

    def __str__(self):
        return self.label or self.code


class Role(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=64)
    description = models.CharField(max_length=255, blank=True)
    is_system = models.BooleanField(default=False, help_text="System roles cannot be deleted.")
    permissions = models.ManyToManyField(AppPermission, blank=True, related_name="roles")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def permission_codes(self):
        return set(self.permissions.values_list("code", flat=True))


class User(AbstractUser):
    """Application user. Roles drive permissions; see permissions_catalog."""
    role = models.ForeignKey(Role, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="users")
    employee_code = models.CharField(max_length=32, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    default_warehouse = models.ForeignKey(
        "masters.Warehouse", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="default_users",
        help_text="Pre-selected in transaction and scanner screens.")
    allowed_warehouses = models.ManyToManyField(
        "masters.Warehouse", blank=True, related_name="permitted_users",
        help_text="Leave empty to allow all warehouses.")
    extra_permissions = models.ManyToManyField(
        AppPermission, blank=True, related_name="granted_users",
        help_text="Permissions granted on top of the user's role.")
    denied_permissions = models.ManyToManyField(
        AppPermission, blank=True, related_name="denied_users",
        help_text="Permissions revoked from this user even if the role grants them.")
    must_change_password = models.BooleanField(default=False)
    last_activity = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["username"]

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def is_super_admin(self):
        return self.is_superuser or (self.role_id and self.role.code == "SUPER_ADMIN")

    def effective_permissions(self):
        if self.is_super_admin:
            return set(PERMISSION_LABELS.keys())
        codes = set()
        if self.role_id and self.role.is_active:
            codes |= self.role.permission_codes
        codes |= set(self.extra_permissions.values_list("code", flat=True))
        codes -= set(self.denied_permissions.values_list("code", flat=True))
        return codes

    def has_perm_code(self, code):
        if not self.is_authenticated or not self.is_active:
            return False
        if self.is_super_admin:
            return True
        return code in self.effective_permissions()

    def warehouse_queryset(self):
        from masters.models import Warehouse
        qs = Warehouse.objects.filter(is_active=True)
        if self.is_super_admin:
            return qs
        allowed = self.allowed_warehouses.all()
        return qs.filter(pk__in=allowed.values("pk")) if allowed.exists() else qs

    def can_use_warehouse(self, warehouse):
        if warehouse is None:
            return False
        if self.is_super_admin:
            return True
        allowed = self.allowed_warehouses.all()
        return (not allowed.exists()) or allowed.filter(pk=warehouse.pk).exists()


class AuditLog(models.Model):
    """Immutable activity trail (section 29)."""

    class Action(models.TextChoices):
        LOGIN = "LOGIN", "Login"
        LOGIN_FAILED = "LOGIN_FAILED", "Failed login"
        LOGOUT = "LOGOUT", "Logout"
        CREATE = "CREATE", "Create"
        UPDATE = "UPDATE", "Update"
        DELETE = "DELETE", "Delete"
        INWARD = "INWARD", "Inward stock"
        OUTWARD = "OUTWARD", "Outward stock"
        TRANSFER = "TRANSFER", "Stock transfer"
        ADJUSTMENT = "ADJUSTMENT", "Stock adjustment"
        OPENING = "OPENING", "Opening stock"
        REVERSAL = "REVERSAL", "Document reversal"
        BARCODE = "BARCODE", "Barcode generated"
        LABEL_PRINT = "LABEL_PRINT", "Label printed"
        IMPORT = "IMPORT", "Data import"
        EXPORT = "EXPORT", "Data export"
        BACKUP = "BACKUP", "Backup"
        RESTORE = "RESTORE", "Restore"
        SETTINGS = "SETTINGS", "Settings changed"
        USER_CHANGE = "USER_CHANGE", "User changed"
        API = "API", "API call"
        SYNC = "SYNC", "ERPNext sync"

    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="audit_logs")
    username_snapshot = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=20, choices=Action.choices, db_index=True)
    object_type = models.CharField(max_length=64, blank=True, db_index=True)
    object_id = models.CharField(max_length=64, blank=True, db_index=True)
    object_label = models.CharField(max_length=255, blank=True)
    document_number = models.CharField(max_length=64, blank=True, db_index=True)
    quantity = models.DecimalField(max_digits=16, decimal_places=3, null=True, blank=True)
    description = models.TextField(blank=True)
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-timestamp", "-id"]
        indexes = [
            models.Index(fields=["-timestamp", "action"]),
            models.Index(fields=["object_type", "object_id"]),
        ]

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} {self.username_snapshot} {self.action}"
