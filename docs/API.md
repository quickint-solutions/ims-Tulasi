# REST API

Base URL: `https://<host>/api/v1/`

**Quantity only.** No endpoint accepts or returns a price, rate, cost, amount, tax or
currency field.

---

## Authentication

Issue a key at **Integration → API Keys**. The plaintext is shown once; only a SHA-256
hash is stored.

```bash
curl -H "Authorization: ApiKey sk_xxxxxxxxxxxxxxxxxxxx" \
     https://host/api/v1/items/

# X-API-Key works too
curl -H "X-API-Key: sk_xxxxxxxxxxxxxxxxxxxx" https://host/api/v1/items/
```

A key carries scopes (`read`, or `read` + `write`) and is bound to a user. **Both** must
allow an operation: the key needs the `write` scope, and the user's role needs the
matching application permission. A key may also carry an IP allow-list, an expiry and
its own rate limit.

Session auth (a logged-in browser) and DRF tokens also work.

---

## Item API

| Method | Path | Permission |
|---|---|---|
| `GET` | `/items/` | `item.view` |
| `GET` | `/items/{id}/` | `item.view` |
| `POST` | `/items/` | `item.change` |
| `PUT` / `PATCH` | `/items/{id}/` | `item.change` |
| `DELETE` | `/items/{id}/` | `item.change` — **deactivates**, never destroys history |
| `GET` | `/items/{id}/stock/` | `stock.view` |
| `GET` | `/items/{id}/movements/` | `stock.view` |

Query parameters: `search`, `category`, `sub_category`, `is_active`, `manufacturer`,
`uom`, `stock_status=low|out`, `ordering`, `page`, `summary=1`.

```json
GET /api/v1/items/12/
{
  "id": 12,
  "item_number": "SP-001",
  "name": "BOILER FEED PUMP IMPELLER",
  "category_name": "Pump Spares",
  "manufacturer": "KSB",
  "material": "SS 316",
  "weight": "12.500", "weight_unit": "KG",
  "size": "250", "size_unit": "MM",
  "uom_code": "NOS",
  "minimum_stock": "2.000", "reorder_level": "4.000", "maximum_stock": "20.000",
  "barcode_number": "SP-001",
  "qr_url": "https://host/i/ngrFc5le8CAMvZzLesGZaQ/",
  "total_quantity": "99.000",
  "stock_status": "IN_STOCK",
  "stock_by_location": [
    {"warehouse_name": "Main Warehouse", "location_code": "MAIN/RACK-A/C-02/T-02",
     "rack": "RACK-A", "column": "C-02", "table": "T-02",
     "quantity": "39.000", "available_quantity": "39.000"}
  ]
}
```

## Category, Warehouse, Location APIs

`/categories/`, `/warehouses/`, `/locations/`, `/racks/`, `/columns/`, `/tables/`,
`/uom/` — all full CRUD, gated on `category.manage`, `warehouse.manage` and
`location.manage`. `GET /warehouses/{id}/stock/` returns that warehouse's holdings.

## Stock API

`GET /stock/` — current balances. Filters: `item`, `item_number`, `warehouse`,
`location`, `hide_zero=0|1`.

`GET /movements/` — the ledger, read-only by design. Filters: `item`, `warehouse`,
`location`, `movement_type`, `document_type`, `document_number`, `date_from`, `date_to`.

## Transaction endpoints

All five take a **manually supplied** `document_number`. Items and locations may be
given as a numeric id, an item number / location code, or a barcode.

| Path | Permission |
|---|---|
| `POST /stock/inward/` | `inward.add` |
| `POST /stock/outward/` | `outward.add` |
| `POST /stock/transfer/` | `transfer.add` |
| `POST /stock/adjustment/` | `adjustment.add` |
| `POST /stock/opening/` | `opening.add` |

```bash
curl -X POST -H "Authorization: ApiKey sk_xxx" -H "Content-Type: application/json" \
  -d '{
        "document_number": "GRN-1042",
        "document_date": "2026-09-02",
        "warehouse": "MAIN",
        "supplier": "Shakti Traders",
        "reference_number": "PO-2044",
        "lines": [
          {"item": "SP-001", "location": "MAIN/RACK-A/C-01/T-03", "quantity": "25"},
          {"item": "GASK-101", "location": "MAIN/RACK-B/C-02/T-01", "quantity": "100"}
        ]
      }' \
  https://host/api/v1/stock/inward/
```

```json
201 Created
{"id": 55, "document_number": "GRN-1042", "document_date": "2026-09-02",
 "status": "POSTED", "total_quantity": "125.000"}
```

Pass `"post": false` to create a draft instead of moving stock.

**Transfer** lines use `from_location` and `to_location`.
**Adjustment** lines use `physical_quantity` (the counted figure); the system works out
the difference against the system quantity at posting time.

### Errors

| Status | Meaning |
|---|---|
| `400` | Validation error — unknown item/location/warehouse, duplicate document number, bad quantity |
| `401` | Missing, unknown, expired or revoked API key |
| `403` | Key is read-only, IP not allowed, or the user's role lacks the permission |
| `404` | Barcode or QR token not registered |
| `409` | `insufficient_stock` — the issue would take a bin below zero |
| `429` | Rate limit exceeded |

```json
409 Conflict
{"detail": "Insufficient stock: SP-001 at MAIN/RACK-A/C-01/T-03 has 12 NOS, tried to issue 40.",
 "code": "insufficient_stock"}
```

## Barcode and QR APIs

```
GET /api/v1/barcode/{code}/   # what a hardware scanner calls; matches barcode or item number
GET /api/v1/qr/{token}/       # resolves the opaque token printed on the label
```

Both return the full item payload. `/barcode/` has its own, higher rate-limit bucket
(`SCAN_RATE_LIMIT`, default 600/minute) so a busy store counter is never throttled.

---

## ERPNext integration

Configure at **Integration → ERPNext**: URL, API key and secret, company, default
warehouse, sync mode (disabled / push / pull / two-way) and which entities to sync.
**Test connection** and **Sync now** are on the same screen; results land in the sync log.

The push mapping, quantities only:

| This system | ERPNext |
|---|---|
| `Item` | `Item` — `item_code`, `item_name`, `item_group`, `stock_uom`, `barcodes[]`, `weight_per_unit` |
| `ItemCategory` | `Item Group` |
| `Warehouse` | `Warehouse` |
| Inward | `Stock Entry` — *Material Receipt* |
| Outward | `Stock Entry` — *Material Issue* |
| Transfer | `Stock Entry` — *Material Transfer* |

No `valuation_rate`, `basic_rate` or amount field is ever sent. The application is fully
functional with the integration disabled — nothing in the stock engine depends on it.

To integrate from the ERPNext side instead, call this API directly: issue a key with the
`write` scope and post to the transaction endpoints above.
