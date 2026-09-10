# Hosting on cPanel

Runs the system on a normal cPanel hosting account, on your own domain, over HTTPS —
so label QR codes open from any phone, including mobile data.

---

## 0. Check this first — it decides everything

**cPanel → Software → does "Setup Python App" exist?**

- **Yes** → follow this guide.
- **No** → Django cannot run on that account. cPanel without the Python app manager
  serves only PHP and static files. You would need a different plan or a small VPS
  (see `INSTALLATION.md`). Do not spend hours before checking this.

Also confirm:

| Need | Where to check |
|---|---|
| Python 3.11 or newer | Setup Python App → Python version dropdown |
| MySQL database | cPanel → MySQL® Databases |
| SSH or Terminal | cPanel → Terminal (some hosts disable it — see §7) |
| SSL certificate | cPanel → SSL/TLS Status (AutoSSL is usually on) |

Known to work: Hostinger Business+, Namecheap Stellar Plus, A2 Hosting, GreenGeeks,
most CloudLinux-based hosts. Known **not** to work: GoDaddy Economy, Bluehost Basic,
and any "PHP-only" plan.

---

## 1. Create the database

**cPanel → MySQL® Databases**

1. New Database: `spares` → Create. cPanel prefixes it, giving something like
   `tulsi_spares`.
2. New User: `spuser` with a strong password → Create. Again prefixed: `tulsi_spuser`.
3. Add User To Database → select both → **ALL PRIVILEGES** → Make Changes.

Write down the three **prefixed** names. The prefix trips almost everyone up.

---

## 2. Upload the application

**cPanel → File Manager**, go to your home directory (`/home/username`), **not**
`public_html`.

1. Create a folder `spares`.
2. Upload `spares-inventory-system.zip` into it.
3. Right-click the zip → **Extract**.
4. If extracting produced `spares/spares/manage.py`, move the inner contents up one
   level. You want `/home/username/spares/manage.py`.

Keeping the code outside `public_html` means nobody can download your `.env` or
database by guessing a URL.

---

## 3. Create the Python app

**cPanel → Setup Python App → Create Application**

| Field | Value |
|---|---|
| Python version | 3.11 or newer |
| Application root | `spares` |
| Application URL | your domain (or a subdomain such as `inventory.yourdomain.com`) |
| Application startup file | `passenger_wsgi.py` |
| Application Entry point | `application` |

Click **Create**. cPanel builds a virtualenv and shows a command near the top of the
page that looks like:

```
source /home/username/virtualenv/spares/3.11/bin/activate && cd /home/username/spares
```

**Copy that line** — every command below is run after it.

---

## 4. Install the components

**cPanel → Terminal** (or SSH), then paste the activate command from step 3, then:

```bash
pip install --upgrade pip
pip install -r requirements-cpanel.txt
```

Use `requirements-cpanel.txt`, not `requirements.txt`. It swaps the PostgreSQL driver
for PyMySQL, which is pure Python and installs without a compiler — shared hosts do not
give you one.

---

## 5. Configure

Create `/home/username/spares/.env` (File Manager → +File, then Edit) with:

```ini
DJANGO_SECRET_KEY=paste-a-long-random-string-here
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=inventory.yourdomain.com,yourdomain.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://inventory.yourdomain.com
TIME_ZONE=Asia/Kolkata

DB_ENGINE=mysql
DB_NAME=tulsi_spares
DB_USER=tulsi_spuser
DB_PASSWORD=the-password-you-set
DB_HOST=localhost
DB_PORT=3306

# The address printed into every label QR code. Use https, and your real domain.
PUBLIC_BASE_URL=https://inventory.yourdomain.com

SERVE_MEDIA=1
SECURE_SSL_REDIRECT=1
```

Generate the secret key in Terminal:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Use the **prefixed** database and user names from step 1.

---

## 6. Set it up

Still in Terminal, with the virtualenv active:

```bash
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py seed_defaults
python manage.py createsuperuser
```

Then **cPanel → Setup Python App → Restart**.

Open `https://inventory.yourdomain.com` and sign in.

---

## 7. If your host has no Terminal or SSH

Some shared plans disable it. The Setup Python App page has an **"Execute python
script"** box that runs a file inside the virtualenv. Create `setup_once.py` in the
application root:

```python
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from django.core.management import call_command
from django.contrib.auth import get_user_model

call_command("migrate", interactive=False)
call_command("collectstatic", interactive=False, verbosity=0)
call_command("seed_defaults")

User = get_user_model()
if not User.objects.filter(username="admin").exists():
    from accounts.models import Role
    User.objects.create_superuser(
        "admin", "you@yourdomain.com", "ChangeThisNow!123",
        role=Role.objects.filter(code="SUPER_ADMIN").first())
    print("admin created - change the password immediately after signing in")
print("setup complete")
```

Run it from that box, sign in, **change the password at once**, then delete
`setup_once.py`.

---

## 8. HTTPS

**cPanel → SSL/TLS Status** → tick the domain → **Run AutoSSL**. Most hosts do this
automatically within the hour.

Confirm `https://` works before printing labels. With `SECURE_SSL_REDIRECT=1` the site
forces HTTPS, so a missing certificate looks like a broken site.

---

## 9. Before printing labels

The QR code has the full URL baked into the sticker, so settle the address now:

- Use the **domain**, never an IP.
- Use **https**.
- Decide between `yourdomain.com` and `inventory.yourdomain.com` and keep it.

Print one label, scan it with a phone **on mobile data** (not office Wi-Fi — that is the
whole point of cloud hosting), confirm the product page opens, then print the rest.

---

## 10. Backups

cPanel → Cron Jobs, once a day:

```
0 2 * * * /home/username/virtualenv/spares/3.11/bin/python /home/username/spares/manage.py backup_now --scheduled --keep 30
```

That writes zips into `spares/backups/`, also listed under Settings → Backup & Restore.
Download them off the server regularly — and keep your host's own account backup
switched on as a second layer.

---

## 11. After any code change

```bash
source /home/username/virtualenv/spares/3.11/bin/activate && cd /home/username/spares
pip install -r requirements-cpanel.txt
python manage.py migrate
python manage.py collectstatic --noinput
```

Then Restart in Setup Python App. Passenger also restarts if you run
`touch tmp/restart.txt` in the application root.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| 500 error, blank page | Setup Python App → open the log file it names. Nine times out of ten it is a wrong DB name/prefix in `.env`. |
| "DisallowedHost" | Add the exact domain to `DJANGO_ALLOWED_HOSTS`. |
| CSS missing, page looks like plain text | `collectstatic` was not run, or was run before `.env` existed so it saw different settings. Re-run it, then Restart. `python manage.py check` says so explicitly. |
| Logo and product images 404 | `SERVE_MEDIA=1` must be in `.env`, and `media/` must be writable (755). |
| "Access denied for user" | The prefixed username, or the user was never added to the database in step 1. |
| CSRF verification failed | Add `https://yourdomain.com` to `DJANGO_CSRF_TRUSTED_ORIGINS`. |
| Changes do nothing | Restart the app. Passenger caches the loaded code. |
| Excel export of a huge report fails | Shared hosts cap memory per process. Narrow the date range, or move to a VPS. |

---

## Honest limits of shared hosting

It works, and for a single store with a handful of users it works well. But:

- **Memory is capped** per process. Big Excel exports and large label batches are the
  first things to hit it.
- **CPU is shared.** Response times vary with what other accounts on the box are doing.
- **No control over restarts.** The host may recycle your app at any time. Harmless
  here — nothing long-running — but worth knowing.
- **Backups are on the same disk** unless you pull them off.

If the store grows past roughly ten simultaneous users, or you start printing thousands
of labels a week, a €5–10/month VPS running the Docker setup in `INSTALLATION.md` is
both faster and easier to reason about.
