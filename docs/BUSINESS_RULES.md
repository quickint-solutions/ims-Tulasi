# Critical business rules and where each is enforced

The 25 rules from the specification, mapped to the code that keeps them true.
A rule with a test reference is verified on every `manage.py test` run.

| # | Rule | Enforced in | Test |
|---|---|---|---|
| 1–7 | No price, amount, cost, GST, profit, sales value or purchase value | No such field exists in any model, form, serializer, report or export | `core.tests.NoMoneyAnywhereTests` (fails the build if one is added) |
| 8 | Quantity only | `stock/models.py`, `stock/services.py`, `reports/definitions.py` | `stock.tests.StockEngineTests` |
| 9 | Manual part numbers | `items.models.Item.item_number` — free-form, validated for shape only | `items.tests.test_free_form_part_numbers_are_accepted` |
| 10 | No mandatory yearly numbering | `core.utils.suggest_document_number` only *suggests*; the field stays editable | `stock.tests.test_manual_document_numbers_are_free_form` |
| 11 | Manual document numbers | `stock.forms.DocumentFormMixin`, `api.serializers._DocumentSerializer` | same as above |
| 12 | Multiple warehouses, independent stock | `masters.models.Warehouse`, `StockBalance` unique on `(item, location)` | `stock.tests.test_transfer_moves_between_warehouses_without_changing_the_total` |
| 13 | Rack + Column + Table location | `masters.models` `Rack` → `RackColumn` → `RackTable` → `Location` | `stock.tests.test_location_code_is_built_from_the_hierarchy` |
| 14 | Barcode drives stock movement | `labels/views.py` scanner, `items.views.global_search`, `api` barcode endpoint | `labels.tests.ScannerTests` |
| 15 | QR code opens product details | `items.views.public_item`, opaque `qr_token` | `labels.tests.PublicQrPageTests` |
| 16 | 50 mm × 25 mm label | `static/css/label.css` (fixed in mm), `LabelTemplate` defaults | `labels.tests.test_default_template_is_50_by_25_mm`, `test_label_css_pins_the_physical_size` |
| 17 | Product name printed on the label | `templates/labels/_label.html` area 3 | `labels.tests.test_preview_page_renders_the_label_at_true_size` |
| 18 | "SCAN TO VIEW PRODUCT DETAILS" on the label | `LabelTemplate.scan_hint_text`, area 1 | same |
| 19 | Monthly/yearly Excel reports | `reports/definitions.py`, `core/excel.py` | `core.tests.test_every_report_renders_and_exports` |
| 20 | Multi-user | `accounts.models.User` | `core.tests.PermissionTests` |
| 21 | Role / permission system | `accounts/permissions_catalog.py` — 38 permissions, 4 seeded roles, per-user overrides | `core.tests.PermissionTests` |
| 22 | Backup / restore | `core/backup.py`, `manage.py backup_now` | `core.tests.BackupTests.test_backup_round_trip` |
| 23 | Product image / document upload | `items.models.ItemImage`, `ItemDocument`, validated extensions and size | — |
| 24 | ERPNext API ready | `api/` (REST) and `integration/erpnext.py` | `api.tests.ApiTests` |
| 25 | Cloud hosting ready | `Dockerfile`, `docker-compose.yml`, `.env.example`, `INSTALLATION.md` | — |

---

## The two rules that shape the schema

### Stock is derived, never typed

Specification §49. `StockBalance.quantity` is a maintained cache, not a source of truth.
The only code that writes it is `stock/services.py:apply_movement`, which:

1. takes a row lock on the `(item, location)` balance,
2. refuses to go below zero unless the document carries `allow_negative` **and** the
   acting user holds the `stock.negative_override` permission,
3. writes an immutable `StockMovement` row recording the quantity, the direction and
   the resulting balance,
4. moves the balance with an `F()` expression inside the same transaction.

`recalculate_balances()` rebuilds every balance by summing `quantity * direction` over
the ledger, so the cache is always reconcilable against history.
`stock.tests.test_recalculate_balances_repairs_a_tampered_row` proves it.

### Movements are never deleted

Specification §22. `StockMovement.delete()` raises. A posted document is reversed, which
writes an equal and opposite `CORRECTION` row against each original and marks the
document cancelled. The original rows stay in the ledger for audit.
`stock.tests.test_reversal_keeps_the_original_rows_and_restores_the_balance` covers it.

---

## Where the logo goes

The logo is for the **application presentation only**:

| Place | Logo? |
|---|---|
| Sidebar header | Yes |
| Sign-in screen | Yes |
| Printed reports and document print-outs | Yes |
| 50 × 25 mm barcode label | **No** |
| Public product page opened by the QR code | **No** |

The label's 1,250 mm² is reserved for the QR code, the Code 128 barcode, the item
number and the item name — what the label exists to carry. The product page opened by
the QR is a plain specification sheet. Settings → Company states both on screen so
nobody wonders where the logo went.

---

## What the public QR page may show

The QR link is genuinely public: anyone holding the printed sticker can open it, staff
and customers alike. The page therefore carries **product details only** —
item number, name, category, make, model, material, grade, weight, size, dimensions,
colour, type, application, specification, drawing / OEM / alternate numbers, unit,
the product image, and any documents explicitly marked public.

It never shows:

- stock quantity,
- warehouse, rack, column or table location,
- suppliers, customers or destinations,
- document numbers, users or movement history,
- internal database ids (the URL carries an opaque `qr_token` instead).

Staff see stock and location on the internal scanner and item pages after signing in.
`labels.tests.test_public_page_shows_product_details_only_by_default` fails the build if
either figure reappears; `test_the_internal_scanner_still_shows_stock_and_location`
fails if hiding them ever breaks the warehouse workflow.

An administrator can switch stock and location back on for a closed network at
**Settings → System Settings**, and can disable the public page entirely.

---

## Barcode integrity

A barcode that *looks* like a barcode but does not scan is worse than no barcode: it is
discovered only when a storeman is standing at a rack with a scanner that will not beep.

`python-barcode` emits an SVG sized in millimetres whose bars are also positioned in
millimetres, while an SVG `viewBox` is unitless. Reconciling the two is not optional —
get it wrong and every symbol is laid out 3.78× too wide and silently truncated after
the first quarter. `labels.generators._responsive_svg` handles it, and three tests hold
it in place:

| Test | Guarantees |
|---|---|
| `test_every_bar_falls_inside_the_canvas` | No symbol is clipped, for eight representative part numbers |
| `test_no_millimetre_units_leak_into_the_viewbox_coordinate_space` | The unit mismatch cannot come back |
| `test_rendered_barcode_decodes_back_to_the_item_number` | The rendered image actually decodes as CODE128 — the real test |

The decode test rasterises the SVG the way a browser would and reads it with `pyzbar`.
It skips cleanly where `libzbar` is not installed; the geometry tests always run.
