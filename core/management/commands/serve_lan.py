"""Run the system on this machine's LAN address and print the URL to share.

For on-premise use: staff open the printed URL from any PC or phone on the same
network, and label QR codes point at the same address.
"""
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from core.network import detect_lan_ip, is_private


class Command(BaseCommand):
    help = "Serve on 0.0.0.0 and report the LAN URL that phones and PCs should use."

    def add_arguments(self, parser):
        parser.add_argument("--port", default="8000")
        parser.add_argument("--no-migrate", action="store_true",
                            help="Skip the automatic migrate/seed step.")

    def handle(self, *args, **options):
        port = options["port"]
        ip = detect_lan_ip()
        url = f"http://{ip}:{port}"

        if not options["no_migrate"]:
            call_command("migrate", verbosity=0, interactive=False)
            call_command("seed_defaults", verbosity=0)

        line = "=" * 62
        self.stdout.write(self.style.SUCCESS(f"\n{line}"))
        self.stdout.write(self.style.SUCCESS("  SPARES INVENTORY - running on your local network"))
        self.stdout.write(self.style.SUCCESS(line))
        self.stdout.write(f"  On this PC        : http://127.0.0.1:{port}")
        self.stdout.write(self.style.SUCCESS(f"  On the network    : {url}"))
        self.stdout.write(f"  Label QR codes    : {settings.PUBLIC_BASE_URL}")
        if settings.PUBLIC_BASE_URL.rstrip("/") != url:
            self.stdout.write(self.style.WARNING(
                "  ! PUBLIC_BASE_URL does not match this machine's address.\n"
                "    Printed QR codes will point somewhere else. Fix it in .env."))
        if not is_private(ip):
            self.stdout.write(self.style.WARNING(
                "  ! No private LAN address found - are you connected to the network?"))
        self.stdout.write(line)
        self.stdout.write("  Phones must be on the SAME Wi-Fi/LAN to open QR links.")
        self.stdout.write("  Allow Python through the Windows firewall when prompted.")
        self.stdout.write("  Give this PC a fixed IP before printing labels in bulk -")
        self.stdout.write("  a DHCP change would orphan every sticker already on a shelf.")
        self.stdout.write(f"{line}\n")

        call_command("runserver", f"0.0.0.0:{port}", use_reloader=False)
