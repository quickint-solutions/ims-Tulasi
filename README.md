# Spares Inventory Management System

A quantity-based warehouse system for industrial spare parts: item master, multi-warehouse
stock with rack/column/table locations, barcode and QR labels at 50 × 25 mm, a
scanner-first workflow, a full movement ledger, 20 reports with Excel export, role-based
users, backup/restore, and a REST API ready for ERPNext.

> **No money, anywhere.** There is no price, cost, rate, amount, GST, tax, discount,
> profit, margin or currency field in the database, the UI, the reports or the API.
> A test (`core.tests.NoMoneyAnywhereTests`) fails the build if one is ever added.

---

## Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Django 5 + Django REST Framework | Batteries included; DRF gives the ERPNext-ready API for free |
| Database | PostgreSQL, MySQL or SQLite | Proper constraints, indexes and transactions; the full suite is run against PostgreSQL-style and MySQL backends |
| Frontend | Django templates + hand-written CSS/JS | No build step, no CDN — works on an isolated plant network |
| Barcode | `python-barcode` (Code 128) | Mature, MIT |
| QR | `qrcode` | Mature, BSD |
| Excel | `openpyxl` | Mature, MIT |
| Serving | Gunicorn + WhiteNoise + nginx | Standard, portable |
| Deploy | Docker Compose | Runs on any VPS, PaaS or on-prem box |

Full list with licences and project links: [`docs/LIBRARIES.md`](docs/LIBRARIES.md).

---

## Modules

**Inventory** — item master (40+ specification fields plus admin-defined custom fields),
categories and sub-categories, units of measure, product images and documents.

**Warehouses** — many warehouses, each with independent stock; `Warehouse → Rack →
Column → Table → Location`; a bulk grid builder; the same item may sit in any number of
bins at once.

**Transactions** — inward, outward, transfer, adjustment and opening stock. Every
document number is typed by the user (`IN-001`, `GRN-125`, `2026-458`, `MANUAL-001` —
no yearly numbering is imposed). Documents are drafts until posted; posting writes the
ledger. Posted documents are never deleted, only reversed with contra entries.

**Barcode & labels** — Code 128 barcode plus a QR code per item, a true 50 × 25 mm
label with a live preview, batch printing, print history and a printer-settings screen
that hard-codes no printer model.

**Scanner** — a full-screen scan field that works with any USB/Bluetooth keyboard-wedge
scanner, and one-tap inward / outward / transfer from the scanned item.

**Public QR page** — scanning a label with a phone opens a mobile-friendly page
addressed by an opaque token, showing **product details only**. Stock quantity and bin
location are deliberately off: the link is public, so customers and visitors can open it
too. Staff see stock and location on the internal scanner and item pages. Both figures
can be switched on for a closed network, and the page can be disabled entirely.

**Reports** — 20 reports (stock, transactions, movement, monthly/yearly, alerts) with
date, item, category, warehouse, rack, column, table, movement-type, user and document
filters, plus Excel export and monthly/yearly report packs.

**Branding** — the company logo appears in the sidebar, on the sign-in screen and on
printed reports. It is deliberately absent from the 50 × 25 mm label and from the public
product page.

**Administration** — four seeded roles (Super Admin, Admin, Store Manager, Store User)
over 38 individually assignable permissions, per-user grants and denials, warehouse
scoping, a complete activity log, and backup/restore.

**Integration** — REST API with API-key auth, scopes, IP allow-lists, rate limiting and
a request log; ERPNext settings, connection test, push sync and sync log. The
application is fully functional with the integration switched off.

---

## Stock model

```
Current stock = Opening + Inward − Outward ± Adjustment ± Transfer
```

Stock is never a hand-editable number. Every change is posted through
`stock/services.py`, which writes an immutable `StockMovement` row (with the balance
after it) and updates a `StockBalance` cache under a row lock. `recalculate_balances()`
rebuilds the cache from the ledger, so the two can always be reconciled.

---

## Getting started

```bash
cp .env.example .env && nano .env
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

**Running it on one PC on your own network instead?** Double-click
`start-windows.bat` (or `./start-linux.sh`). It installs everything on first run and
prints the LAN address for phones and other PCs. See
[`docs/LOCAL_HOSTING.md`](docs/LOCAL_HOSTING.md).

Full instructions, including a manual (non-Docker) install: [`INSTALLATION.md`](INSTALLATION.md).

To explore with sample data:

```bash
python manage.py seed_defaults
python manage.py seed_demo     # 20 items, 3 warehouses, 54 bins, ~6 months of movement
```

---

## Tests

```bash
python manage.py test
```

86 tests covering the stock arithmetic, insufficient-stock guards, reversals, ledger
immutability, label geometry, the public QR page, permissions per role, import/export,
backup round-trip, every page and every report, the whole API, and the no-money rule.

---

## Documentation

| File | Contents |
|---|---|
| [`INSTALLATION.md`](INSTALLATION.md) | Deployment, HTTPS, backups, upgrades, troubleshooting |
| [`docs/LOCAL_HOSTING.md`](docs/LOCAL_HOSTING.md) | Running it on one PC on your own LAN, fixed IP, firewall |
| [`docs/CPANEL_HOSTING.md`](docs/CPANEL_HOSTING.md) | Shared cPanel hosting: Setup Python App, MySQL, HTTPS |
| [`docs/API.md`](docs/API.md) | REST endpoints, auth, examples, ERPNext integration |
| [`docs/BUSINESS_RULES.md`](docs/BUSINESS_RULES.md) | The 25 rules that must not change, and where each is enforced |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Schema, module map, request flow |
| [`docs/LIBRARIES.md`](docs/LIBRARIES.md) | Every third-party library, its licence and project link |
