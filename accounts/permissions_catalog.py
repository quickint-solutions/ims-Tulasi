"""Central catalogue of application permissions (section 28).

Permissions are data, not code: they are seeded into the database so an
administrator can re-assign them per role from the UI.
"""

PERMISSION_GROUPS = [
    ("Inventory", [
        ("item.view", "View items"),
        ("item.add", "Create items"),
        ("item.change", "Edit items"),
        ("item.delete", "Deactivate items"),
        ("item.import", "Import item master"),
        ("item.export", "Export item master"),
        ("category.manage", "Manage categories"),
    ]),
    ("Warehouse", [
        ("warehouse.view", "View warehouses"),
        ("warehouse.manage", "Manage warehouses"),
        ("location.view", "View locations"),
        ("location.manage", "Manage racks, columns, tables and locations"),
    ]),
    ("Transactions", [
        ("stock.view", "View stock and ledger"),
        ("inward.add", "Create inward"),
        ("outward.add", "Create outward"),
        ("transfer.add", "Create stock transfer"),
        ("adjustment.add", "Create stock adjustment"),
        ("adjustment.approve", "Approve stock adjustment"),
        ("opening.add", "Enter opening stock"),
        ("stock.negative_override", "Allow outward beyond available stock"),
        ("stock.reverse", "Reverse or correct a posted document"),
    ]),
    ("Barcode", [
        ("barcode.view", "View barcodes and labels"),
        ("barcode.generate", "Generate barcodes and QR codes"),
        ("barcode.print", "Print and reprint labels"),
        ("printer.manage", "Manage printer settings"),
        ("scanner.use", "Use the scanner screen"),
    ]),
    ("Reports", [
        ("report.view", "View reports"),
        ("report.export", "Export reports to Excel"),
    ]),
    ("Files", [
        ("file.view", "View product images and documents"),
        ("file.upload", "Upload product images and documents"),
        ("file.delete", "Delete product images and documents"),
    ]),
    ("Administration", [
        ("user.view", "View users"),
        ("user.manage", "Manage users, roles and permissions"),
        ("audit.view", "View activity log"),
        ("backup.manage", "Create, download and restore backups"),
        ("settings.manage", "Manage system settings"),
    ]),
    ("Integration", [
        ("api.manage", "Manage API keys"),
        ("erpnext.manage", "Manage ERPNext integration"),
        ("erpnext.sync", "Run ERPNext synchronisation"),
    ]),
]

ALL_PERMISSIONS = [code for _g, perms in PERMISSION_GROUPS for code, _l in perms]
PERMISSION_LABELS = {code: label for _g, perms in PERMISSION_GROUPS for code, label in perms}

ROLE_SUPER_ADMIN = "SUPER_ADMIN"
ROLE_ADMIN = "ADMIN"
ROLE_STORE_MANAGER = "STORE_MANAGER"
ROLE_STORE_USER = "STORE_USER"

DEFAULT_ROLES = {
    ROLE_SUPER_ADMIN: {
        "name": "Super Admin",
        "description": "Unrestricted access to every module and setting.",
        "permissions": ALL_PERMISSIONS,
    },
    ROLE_ADMIN: {
        "name": "Admin",
        "description": "Manages masters, stock, users, barcodes, reports and settings.",
        "permissions": [p for p in ALL_PERMISSIONS if p not in ("backup.manage",)],
    },
    ROLE_STORE_MANAGER: {
        "name": "Store Manager",
        "description": "Runs day-to-day store operations and prints labels.",
        "permissions": [
            "item.view", "item.add", "item.change", "item.export",
            "warehouse.view", "location.view",
            "stock.view", "inward.add", "outward.add", "transfer.add",
            "adjustment.add", "opening.add",
            "barcode.view", "barcode.generate", "barcode.print", "scanner.use",
            "report.view", "report.export",
            "file.view", "file.upload",
        ],
    },
    ROLE_STORE_USER: {
        "name": "Store User",
        "description": "Scans items and records inward and outward movements.",
        "permissions": [
            "item.view", "warehouse.view", "location.view", "stock.view",
            "inward.add", "outward.add",
            "barcode.view", "scanner.use",
            "report.view", "file.view",
        ],
    },
}
