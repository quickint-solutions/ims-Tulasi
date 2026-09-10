# Installation & Deployment

Spares Inventory Management System — Django 5 + PostgreSQL + Docker.
**Quantity-only.** The system holds no price, cost, tax or value data anywhere.

---

## 1. What you need

| | Minimum | Recommended |
|---|---|---|
| CPU / RAM | 1 vCPU, 1 GB | 2 vCPU, 4 GB |
| Disk | 10 GB | 40 GB (images and backups grow) |
| OS | Any Linux with Docker | Ubuntu 22.04 / 24.04 LTS |
| Database | SQLite (pilot only) | PostgreSQL 14+ |
| TLS | — | Required, so phones can open the QR links |

A 2 vCPU / 4 GB VPS comfortably handles 10,000+ items and 100,000+ stock movements.

---

## 1b. Which guide do you want?

| Where it runs | Guide |
|---|---|
| A VPS or cloud server, with Docker | this file |
| One Windows PC on your own network | [`docs/LOCAL_HOSTING.md`](docs/LOCAL_HOSTING.md) |
| Shared cPanel hosting on your domain | [`docs/CPANEL_HOSTING.md`](docs/CPANEL_HOSTING.md) |

---

## 2. Quick start with Docker (recommended)

```bash
git clone <your-repo-url> spares
cd spares

cp .env.example .env
nano .env                      # set DJANGO_SECRET_KEY, DB_PASSWORD, PUBLIC_BASE_URL, hosts

docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

Open `http://<server>:8000/` and sign in.

`docker compose up` already runs `migrate` and `seed_defaults`, so permissions, roles,
units of measure, the starter categories and the 50 × 25 mm label template are in place.

### Generate a secret key

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

### `PUBLIC_BASE_URL` — read this before printing labels

Every label's QR code encodes `PUBLIC_BASE_URL + /i/<token>/`. That URL is burned into
the printed sticker, so set it to the address staff will reach from their phones
**before** you print a batch. If the server lives only on the plant LAN, phones on
mobile data cannot open those links.

---

## 3. Manual install (no Docker)

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip postgresql nginx git

sudo -u postgres psql -c "CREATE USER spares WITH PASSWORD 'strong-password';"
sudo -u postgres psql -c "CREATE DATABASE spares OWNER spares;"

git clone <your-repo-url> /opt/spares
cd /opt/spares
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env && nano .env
set -a && . ./.env && set +a

python manage.py migrate
python manage.py seed_defaults
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

### systemd service

`/etc/systemd/system/spares.service`:

```ini
[Unit]
Description=Spares Inventory
After=network.target postgresql.service

[Service]
User=www-data
WorkingDirectory=/opt/spares
EnvironmentFile=/opt/spares/.env
ExecStart=/opt/spares/.venv/bin/gunicorn config.wsgi:application \
          --bind 127.0.0.1:8000 --workers 3 --threads 4 --timeout 120
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now spares
```

### nginx

```nginx
server {
    listen 80;
    server_name inventory.example.com;

    client_max_body_size 30M;

    location /static/ { alias /opt/spares/staticfiles/; expires 30d; }
    location /media/  { alias /opt/spares/media/; expires 7d; }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### HTTPS

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d inventory.example.com
```

Then set `PUBLIC_BASE_URL=https://inventory.example.com` and `SECURE_SSL_REDIRECT=1`,
and restart.

---

## 4. First-run checklist

1. **Settings → Company** — company name and logo.
   The logo appears in the app shell, the sign-in screen and printed reports.
   It is deliberately **not** on the 50 × 25 mm barcode label.
2. **Warehouses** — create your warehouses.
3. **Warehouses → Locations → Build rack grid** — generate racks, columns, tables and
   locations in one step.
4. **Inventory → Categories** — 16 starter categories are seeded; edit to taste.
5. **Items** — create manually, or **Items → Import** from Excel (the template
   download includes an optional Opening Quantity column).
6. **Transactions → Opening Stock** — post your starting balances.
7. **Settings → Printer** — add your Seznik Mini (or other) profile, then **Test print**
   and measure the sticker.
8. **Users → Roles** — review the four seeded roles, then create users.

---

## 5. Backups

The **Settings → Backup & Restore** screen creates a single `.zip` holding a full
database dump plus, optionally, every product image and document. Restoring takes an
automatic snapshot of the current data first.

Scheduled backups:

```bash
# Docker Compose already runs a daily backup container.
# For a manual install, add a cron entry:
0 2 * * * cd /opt/spares && .venv/bin/python manage.py backup_now --scheduled --keep 30
```

Copy the backup directory off the server regularly — a backup on the same disk is not
a backup.

---

## 6. Upgrades

```bash
git pull
docker compose build web && docker compose up -d      # Docker
# or, manual:
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl restart spares
```

Take a backup before every upgrade.

---

## 7. Health, logs and troubleshooting

| Symptom | Check |
|---|---|
| `/healthz/` not 200 | Container/service is down: `docker compose logs web` |
| CSS missing | `collectstatic` did not run, or nginx `/static/` alias is wrong |
| QR opens nothing on a phone | `PUBLIC_BASE_URL` is unreachable from mobile data |
| Label prints the wrong size | Printer dialog: paper 50 × 25 mm, margins none, scale 100% |
| "Insufficient stock" on outward | Correct — post an inward or use the admin override |
| CSRF error behind a proxy | Add the site to `DJANGO_CSRF_TRUSTED_ORIGINS` |

Application log: `logs/app.log` (rotating, 5 × 5 MB).
API request log: **Integration → API Logs** in the UI.
Everything a user did: **Users → Activity Log**.

---

## 8. Performance notes

The schema is indexed for the access patterns that matter: item number, barcode,
`(item, movement_date)`, `(warehouse, movement_date)`, `(item, location)` on balances.
Lists are server-side paginated and filtered. Stock is read from a maintained
`stock_balances` table rather than by summing the ledger on every page, and
`recalculate_balances()` can rebuild it from the ledger if the two ever disagree.
