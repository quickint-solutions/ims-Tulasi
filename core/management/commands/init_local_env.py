"""Write a .env suited to hosting on this machine's local network.

Runs once, on the first start. It never touches an existing .env, so anything
the administrator has changed by hand survives every later start-up.
"""
import secrets

from django.core.management.base import BaseCommand

from core.network import detect_lan_ip, is_private

TEMPLATE = """# Spares Inventory - local network install
# Generated on first run. Edit freely; nothing overwrites this file.

DJANGO_SECRET_KEY={secret_key}
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=*
TIME_ZONE={time_zone}

# SQLite keeps the whole database in data/spares.sqlite3 - no server to install.
# Switch to PostgreSQL when more than about five people post transactions at once.
DB_ENGINE=sqlite

# Plain HTTP on the LAN, so the HTTPS redirect must stay off. Turn it back on if
# you ever put this behind nginx or Caddy with a certificate.
SECURE_SSL_REDIRECT=0
SERVE_MEDIA=1

# ---------------------------------------------------------------------------
# THE ADDRESS PRINTED INTO EVERY LABEL QR CODE.
#
# It was detected as {detected} when this file was created. If this PC's IP
# ever changes, every sticker already printed will point nowhere - so give this
# machine a fixed address (DHCP reservation or a static IP) and keep the line
# below in step with it. A hostname is even better if your network has DNS:
#     PUBLIC_BASE_URL=http://inventory.local:8000
#
# Print ONE label, scan it with a phone, confirm the page opens, then print the
# rest.
# ---------------------------------------------------------------------------
PUBLIC_BASE_URL=http://{detected}:{port}
PUBLIC_HOST_PORT={port}
"""


class Command(BaseCommand):
    help = "Create a .env for local-network hosting, if one does not exist yet."

    def add_arguments(self, parser):
        parser.add_argument("--port", default="8000")
        parser.add_argument("--force", action="store_true",
                            help="Overwrite an existing .env. Use with care.")

    def handle(self, *args, **options):
        from django.conf import settings

        path = settings.BASE_DIR / ".env"
        if path.exists() and not options["force"]:
            self.stdout.write(f"{path.name} already exists - leaving it alone.")
            return

        ip = detect_lan_ip()
        path.write_text(TEMPLATE.format(
            secret_key=secrets.token_urlsafe(64),
            time_zone=settings.TIME_ZONE,
            detected=ip,
            port=options["port"],
        ), encoding="utf-8")

        self.stdout.write(self.style.SUCCESS(f"Created {path.name}."))
        self.stdout.write(f"  Label QR codes will point at http://{ip}:{options['port']}")
        if not is_private(ip):
            self.stdout.write(self.style.WARNING(
                "  ! That does not look like a LAN address. Check the network "
                "connection, then correct PUBLIC_BASE_URL in .env."))
