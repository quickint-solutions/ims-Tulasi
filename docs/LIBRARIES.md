# Third-party libraries

Everything here is free and open source. No paid API is used anywhere in the system.

## Runtime (Python)

| Library | Licence | Used for | Project |
|---|---|---|---|
| Django | BSD-3-Clause | Web framework, ORM, auth, migrations, admin | https://github.com/django/django |
| Django REST Framework | BSD-3-Clause | REST API, serializers, throttling | https://github.com/encode/django-rest-framework |
| django-filter | BSD-3-Clause | Query-parameter filtering on API list endpoints | https://github.com/carltongibson/django-filter |
| python-barcode | MIT | Code 128 barcode generation (SVG and PNG) | https://github.com/WhyNotHugo/python-barcode |
| qrcode | BSD-3-Clause | QR code generation for the label and public page | https://github.com/lincolnloop/python-qrcode |
| openpyxl | MIT | Excel export and item-master import | https://foss.heptapod.net/openpyxl/openpyxl |
| Pillow | MIT-CMU | Image handling for product photos and PNG barcodes | https://github.com/python-pillow/Pillow |
| WhiteNoise | MIT | Static file serving from the app process | https://github.com/evansd/whitenoise |
| Gunicorn | MIT | WSGI application server | https://github.com/benoitc/gunicorn |
| psycopg2 | LGPL-3.0 | PostgreSQL driver | https://github.com/psycopg/psycopg2 |

## Infrastructure

| Component | Licence | Project |
|---|---|---|
| PostgreSQL | PostgreSQL Licence | https://github.com/postgres/postgres |
| nginx | BSD-2-Clause | https://github.com/nginx/nginx |
| Docker / Compose | Apache-2.0 | https://github.com/docker/compose |

## Frontend

There is **no** JavaScript framework, no CSS framework and no CDN dependency.
`static/css/app.css`, `static/css/label.css` and `static/js/app.js` are written for this
project and served from the application itself, so every screen works on a network with
no internet access.

Icons are inline SVG paths defined in `templates/partials/icons.html`.

Charts are server-rendered inline SVG (`core/charts.py`) — no charting library.

## Barcode symbology

**Code 128** is used for the printed barcode. It is the common industrial choice:
it encodes the full ASCII set (so part numbers such as `BOILER-FD-001` work as-is),
is compact, and every consumer USB/Bluetooth scanner reads it without configuration.

**QR (model 2, error correction M)** is used for the phone-scannable link. Error
correction M tolerates roughly 15% damage, which matters on a sticker that lives in a
workshop.
