"""Database + media backup and restore (section 30).

A backup is a single .zip holding a Django `dumpdata` JSON of every application
table plus, optionally, the media tree. It restores on any supported database
engine, so a SQLite pilot can be moved onto PostgreSQL unchanged.
"""
import hashlib
import io
import json
import os
import shutil
import zipfile
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core import management
from django.core.management.color import no_style
from django.db import connection, transaction
from django.utils import timezone

APP_LABELS = ["accounts", "masters", "items", "stock", "labels", "core", "api",
              "integration"]
MANIFEST = "manifest.json"
DUMP_NAME = "data.json"
MEDIA_PREFIX = "media/"


def _backup_dir():
    path = Path(settings.BACKUP_ROOT)
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_backup(*, include_media=True, kind="MANUAL", notes="", user=None):
    from .models import Backup

    # Microseconds are included so two backups taken in the same second - which
    # happens when a restore takes its automatic pre-restore snapshot - can never
    # overwrite each other.
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M%S-%f")
    filename = f"spares-backup-{stamp}.zip"
    target = _backup_dir() / filename

    buffer = io.StringIO()
    management.call_command("dumpdata", *APP_LABELS, "auth.Permission",
                            natural_foreign=True, natural_primary=True,
                            indent=1, stdout=buffer)
    payload = buffer.getvalue()

    counts = {}
    for label in APP_LABELS:
        for model in apps.get_app_config(label).get_models():
            counts[f"{label}.{model.__name__}"] = model.objects.count()

    manifest = {
        "created_at": timezone.now().isoformat(),
        "created_by": getattr(user, "username", "system"),
        "django_version": __import__("django").get_version(),
        "apps": APP_LABELS,
        "includes_media": include_media,
        "record_counts": counts,
        "note": "Quantity-only inventory system. No financial data is stored.",
    }

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr(MANIFEST, json.dumps(manifest, indent=2))
        zf.writestr(DUMP_NAME, payload)
        if include_media and Path(settings.MEDIA_ROOT).exists():
            for root, _dirs, files in os.walk(settings.MEDIA_ROOT):
                for name in files:
                    full = Path(root) / name
                    rel = full.relative_to(settings.MEDIA_ROOT)
                    zf.write(full, MEDIA_PREFIX + str(rel))

    checksum = hashlib.sha256(target.read_bytes()).hexdigest()
    return Backup.objects.create(
        filename=filename, path=str(target), size_bytes=target.stat().st_size,
        kind=kind, includes_media=include_media, notes=notes, checksum=checksum,
        created_by=user)


def inspect_backup(file_obj):
    """Read the manifest without applying anything."""
    with zipfile.ZipFile(file_obj) as zf:
        if MANIFEST not in zf.namelist():
            raise ValueError("This zip is not a Spares Inventory backup "
                             "(manifest.json is missing).")
        return json.loads(zf.read(MANIFEST).decode())


@transaction.atomic
def restore_backup(file_obj, *, restore_media=True, user=None):
    """Replace current data with the backup's. A pre-restore snapshot is taken first."""
    from .models import Backup

    # Read the upload into memory first: the pre-restore snapshot writes to the
    # same backup directory, and we must not depend on the source handle staying
    # valid while that happens.
    file_obj.seek(0)
    source = io.BytesIO(file_obj.read())
    manifest = inspect_backup(source)

    create_backup(include_media=True, kind=Backup.Kind.PRE_RESTORE,
                  notes="Automatic snapshot taken before a restore", user=user)

    workdir = _backup_dir() / f"restore-{timezone.now():%Y%m%d%H%M%S}"
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(source) as zf:
            dump_path = workdir / DUMP_NAME
            dump_path.write_bytes(zf.read(DUMP_NAME))

            _clear_application_tables()
            management.call_command("loaddata", str(dump_path))

            if restore_media and manifest.get("includes_media"):
                media_root = Path(settings.MEDIA_ROOT)
                for name in zf.namelist():
                    if not name.startswith(MEDIA_PREFIX) or name.endswith("/"):
                        continue
                    dest = media_root / name[len(MEDIA_PREFIX):]
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(zf.read(name))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return manifest


def _clear_application_tables():
    """Empty every application table, ignoring FK ordering.

    Protected foreign keys exist to stop a user deleting an item that has stock
    history; a restore is a wholesale replacement, so it goes around them with
    the database's own flush rather than the ORM collector.
    """
    from .models import Backup

    tables = []
    for label in APP_LABELS:
        for model in apps.get_app_config(label).get_models():
            if model is Backup:
                continue  # keep the backup catalogue so the pre-restore snapshot survives
            tables.append(model._meta.db_table)
            for field in model._meta.many_to_many:
                through = field.remote_field.through
                if through is not None and through._meta.auto_created:
                    tables.append(through._meta.db_table)

    statements = connection.ops.sql_flush(no_style(), sorted(set(tables)),
                                          allow_cascade=False)
    with connection.constraint_checks_disabled():
        with connection.cursor() as cursor:
            for sql in statements:
                cursor.execute(sql)

    # Backup rows are kept, but the users they pointed at have just been flushed,
    # so drop those references before the fixture's own rows are loaded back.
    Backup.objects.update(created_by=None, updated_by=None)


def delete_backup(backup):
    try:
        Path(backup.path).unlink(missing_ok=True)
    except OSError:
        pass
    backup.delete()
