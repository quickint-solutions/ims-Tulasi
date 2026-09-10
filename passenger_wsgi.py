"""Passenger entry point for cPanel "Setup Python App".

cPanel's Python app manager runs the application through Phusion Passenger, which
imports this file from the application root and looks for a module-level object
named `application`. Nothing else in the project needs to change.

The virtualenv is created and activated by cPanel itself, so there is no
interpreter juggling here - only making sure the project root is importable
before Django starts.
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402  (path set above)

application = get_wsgi_application()
