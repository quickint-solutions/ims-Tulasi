## 2026-09-10

- Added `reset_business_data` management command for destructive inventory/module DB reset.
- Added `reset-business-data.bat` and `reset-business-data.sh` server launchers.
- Scripts run dry-run by default; actual deletion requires first argument `confirm`.
- Reset preserves users, roles, permissions, company/system settings, label/printer templates, API keys, and ERPNext settings.
- Reset deletes item/category data, stock balances/movements/documents, warehouse/rack/location data, label print logs, API logs, sync logs, and audit logs.
- Safety gates: `--dry-run` reports row counts only; `--confirm` creates a backup before deleting.
- Validation earlier: `manage.py check` passed after creating `.venv` and installing `requirements.txt`.
- Current local DB is `data/spares.sqlite3`, but it is 0 bytes/unmigrated; dry-run refused with missing app tables. No business data was deleted in this checkout.
- Next step on server: run the script once without `confirm`, review counts, then run with `confirm` only on the intended DB.
