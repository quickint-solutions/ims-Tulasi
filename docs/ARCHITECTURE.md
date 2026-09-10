# Architecture

## Module map

| App | Responsibility |
|---|---|
| `core` | Company/system settings, dashboard, charts, Excel helper, backup/restore, permission mixins |
| `accounts` | User model, roles, 38-permission catalogue, audit log, login |
| `masters` | Categories, units, warehouses, racks, columns, tables, locations |
| `items` | Item master, images, documents, custom fields, import/export, public QR page |
| `stock` | Balances, the immutable ledger, five document types, the posting engine |
| `labels` | Barcode/QR generation, 50 × 25 mm label, print sheets, printers, scanner |
| `reports` | 20 report definitions, filters, Excel export |
| `api` | REST API, API keys, request log |
| `integration` | ERPNext settings, client, sync log |

## Entity relationships

```
Warehouse ─┬─< Rack ─< RackColumn ─< RackTable
           └─< Location (warehouse, rack?, column?, table?)  ← unique per path & code
                   │
ItemCategory ─< Item ─┬─< ItemImage
      │               ├─< ItemDocument
      └─< (sub)       └─< StockBalance >─ Location        ← unique (item, location)
                          │
UnitOfMeasure ─< Item     └─ StockMovement >─ Location    ← immutable ledger

InwardDocument   ─< InwardItem      ┐
OutwardDocument  ─< OutwardItem     │
TransferDocument ─< TransferItem    ├─ post_document() ─→ StockMovement + StockBalance
AdjustmentDocument ─< AdjustmentItem│
OpeningStockDocument ─< OpeningStockItem ┘

User >─ Role >─< AppPermission        AuditLog >─ User
ApiKey >─ User      ApiLog >─ ApiKey  ErpNextSettings, SyncLog
CompanySettings, SystemSettings, Backup, LabelTemplate, PrinterSetting, LabelPrintLog
```

## Posting a document

```
user submits form / API call
        │
        ▼
  document + lines saved as DRAFT      (no stock has moved)
        │
        ▼
  services.post_document(doc, user)    ── one transaction ──┐
        │                                                    │
        ├─ planner builds (item, location, qty, direction)   │
        ├─ per step: lock balance → check availability       │
        │            → write StockMovement → move balance    │
        ├─ mark document POSTED                              │
        └─ write AuditLog row                          ──────┘
```

Failure at any step rolls the whole thing back — a document is never half-posted.

## Request flow

```
nginx ──→ gunicorn ──→ Django
                        ├─ SecurityMiddleware, WhiteNoise (static)
                        ├─ Session / CSRF / Auth
                        ├─ CurrentUserMiddleware  (acting user for audit)
                        ├─ ApiLoggingMiddleware   (/api/ only)
                        └─ view
                             ├─ AppPermissionRequiredMixin → 403 if not permitted
                             ├─ ORM (PostgreSQL)
                             └─ template  or  DRF serializer
```

## Performance

- Indexes on `item_number`, `barcode_number`, `(item, -movement_date)`,
  `(warehouse, -movement_date)`, `(movement_type, -movement_date)`,
  `(document_type, document_number)`, `(item, warehouse)` and `(warehouse, location)`.
- Every list is server-side filtered and paginated; nothing loads a full table.
- Current stock reads the `stock_balances` table rather than aggregating the ledger.
- Barcode and QR SVGs are cached for 12 hours by value.
- `select_related` / `annotate` on every list view to avoid N+1 queries.

## Security

Session auth for the UI, API-key or token auth for the API. Role-based permission checks
on every view and every API endpoint, plus a `write` scope on the key itself for unsafe
verbs. Passwords hashed with Django's PBKDF2. CSRF on all forms. Upload extension and
size validation. HTTPS, HSTS and secure cookies outside DEBUG. Rate limiting on the API
and a tighter bucket for barcode scans. Full audit trail. The public QR page is
addressed by an opaque token and exposes no internal identifiers, suppliers, users or
documents.
