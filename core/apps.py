from django.apps import AppConfig
from django.core.checks import Warning as CheckWarning
from django.core.checks import register


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        register(check_static_files_collected, "staticfiles")


def check_static_files_collected(app_configs, **kwargs):
    """Say plainly when `collectstatic` has not been run in production.

    Without this the symptom is an unstyled site (or, before the forgiving storage
    class, a 500 on every page) and a message about a "manifest entry" that means
    nothing to whoever is doing the deployment.
    """
    from django.conf import settings

    if settings.DEBUG or getattr(settings, "TESTING", False):
        return []
    backend = settings.STORAGES.get("staticfiles", {}).get("BACKEND", "")
    if "Manifest" not in backend:
        return []
    if (settings.STATIC_ROOT / "staticfiles.json").exists():
        return []
    return [CheckWarning(
        "Static files have not been collected, so the site will render unstyled.",
        hint="Run:  python manage.py collectstatic --noinput\n"
             "Run it with the same settings the server uses - if DEBUG differs "
             "between the two, the manifest is written in the wrong format.",
        id="core.W001",
    )]
