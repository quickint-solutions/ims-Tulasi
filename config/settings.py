"""
Spares Inventory Management System - Django settings.

QUANTITY-ONLY SYSTEM. No price, cost, rate, tax, GST, or currency fields
exist anywhere in this project by design. See docs/BUSINESS_RULES.md.
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path):
    """Read a .env file into the process environment.

    Real environment variables always win, which is what lets Docker Compose,
    systemd and the start scripts override a value without editing the file.
    Deliberately dependency-free - a .env parser is ten lines and not worth a
    package. Without this, editing .env on a manual or on-premise install would
    silently do nothing.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(BASE_DIR / ".env")


def env(key, default=None):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    return str(env(key, str(default))).strip().lower() in ("1", "true", "yes", "on")


def env_list(key, default=""):
    raw = env(key, default) or ""
    return [x.strip() for x in raw.split(",") if x.strip()]


# True while `manage.py test` is running: keeps the suite off HTTPS redirects and
# off the hashed static manifest, which needs collectstatic.
TESTING = "test" in sys.argv or "pytest" in sys.modules

SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-change-me-in-production")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "*")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "rest_framework",
    "rest_framework.authtoken",
    "django_filters",
    "core",
    "accounts",
    "masters",
    "items",
    "stock",
    "labels",
    "reports",
    "api",
    "integration",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "accounts.middleware.CurrentUserMiddleware",
    "api.middleware.ApiLoggingMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.branding",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DB_ENGINE = env("DB_ENGINE", "sqlite").strip().lower()

if DB_ENGINE == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DB_NAME", "spares"),
            "USER": env("DB_USER", "spares"),
            "PASSWORD": env("DB_PASSWORD", "spares"),
            "HOST": env("DB_HOST", "localhost"),
            "PORT": env("DB_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }
elif DB_ENGINE == "mysql":
    # Shared cPanel hosting almost always offers MySQL/MariaDB and nothing else.
    # PyMySQL is used in place of mysqlclient because it is pure Python and so
    # installs without a compiler, which shared hosts rarely provide.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": env("DB_NAME", "spares"),
            "USER": env("DB_USER", "spares"),
            "PASSWORD": env("DB_PASSWORD", ""),
            "HOST": env("DB_HOST", "localhost"),
            "PORT": env("DB_PORT", "3306"),
            "CONN_MAX_AGE": 60,
            "OPTIONS": {
                "charset": "utf8mb4",
                # STRICT_TRANS_TABLES turns silent truncation into an error, which
                # matters for a stock ledger.
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "data" / "spares.sqlite3",
            "OPTIONS": {"timeout": 20},
        }
    }

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", "Asia/Kolkata")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
# The hashed manifest storage needs `collectstatic` to have run, so it is only
# used outside DEBUG and can be turned off for tests. The "forgiving" subclass
# degrades to an unhashed path rather than 500ing the whole site when an entry is
# missing - see core/storage.py.
_STATIC_BACKEND = ("core.storage.ForgivingManifestStaticFilesStorage"
                   if not DEBUG and not TESTING and env_bool("USE_MANIFEST_STATIC", True)
                   else "django.contrib.staticfiles.storage.StaticFilesStorage")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": _STATIC_BACKEND},
}

MEDIA_URL = "media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", str(BASE_DIR / "media")))
# Uploaded images and documents are served by Django unless a real web server is
# doing it. Set SERVE_MEDIA=0 when nginx has a /media/ alias, as in INSTALLATION.md.
SERVE_MEDIA = env_bool("SERVE_MEDIA", True)
if TESTING:
    # Keep uploads and seeded branding out of the real media tree during tests.
    import tempfile
    MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="spares-test-media-"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

SESSION_COOKIE_AGE = int(env("SESSION_COOKIE_AGE", 60 * 60 * 12))
SESSION_EXPIRE_AT_BROWSER_CLOSE = env_bool("SESSION_EXPIRE_AT_BROWSER_CLOSE", False)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "api.auth.ApiKeyAuthentication",
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "api": env("API_RATE_LIMIT", "1000/hour"),
        "scan": env("SCAN_RATE_LIMIT", "600/minute"),
    },
}

# --- File upload safety (section 39/55) ---
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "webp", "gif", "bmp"]
ALLOWED_DOCUMENT_EXTENSIONS = [
    "pdf", "doc", "docx", "xls", "xlsx", "csv", "txt",
    "dwg", "dxf", "step", "stp", "igs", "zip", "png", "jpg", "jpeg",
]
MAX_UPLOAD_SIZE_MB = int(env("MAX_UPLOAD_SIZE_MB", 25))

# --- Label defaults (section 13) ---
LABEL_WIDTH_MM = float(env("LABEL_WIDTH_MM", 50))
LABEL_HEIGHT_MM = float(env("LABEL_HEIGHT_MM", 25))

# --- Public QR base url; used to build the mobile item page link ---
# This string is printed into every label QR code, so it has to be an address
# phones can actually reach. When it is not set explicitly we fall back to this
# machine's LAN address, which makes an on-premise install work out of the box -
# but pin it (static IP, DHCP reservation or a hostname) before printing a batch
# of labels, because a DHCP change would orphan every sticker already on a shelf.
PUBLIC_HOST_PORT = env("PUBLIC_HOST_PORT", "8000")
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", "")
PUBLIC_BASE_URL_IS_AUTODETECTED = not PUBLIC_BASE_URL
if not PUBLIC_BASE_URL:
    from core.network import detect_lan_ip
    _lan_ip = detect_lan_ip()
    PUBLIC_BASE_URL = f"http://{_lan_ip}:{PUBLIC_HOST_PORT}"
PUBLIC_BASE_URL = PUBLIC_BASE_URL.rstrip("/")

BACKUP_ROOT = Path(env("BACKUP_ROOT", str(BASE_DIR / "backups")))

# --- Security (production) ---
if not DEBUG and not TESTING:
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(env("SECURE_HSTS_SECONDS", 31536000))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Nothing in the application is meant to be framed, including the label print sheet.
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"verbose": {"format": "{levelname} {asctime} {name} {message}", "style": "{"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(BASE_DIR / "logs" / "app.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console", "file"], "level": env("LOG_LEVEL", "INFO")},
}

for _p in (BASE_DIR / "logs", BASE_DIR / "data", MEDIA_ROOT, BACKUP_ROOT):
    _p.mkdir(parents=True, exist_ok=True)
