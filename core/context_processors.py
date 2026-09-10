from django.core.cache import cache


def branding(request):
    """Company identity + system switches available in every template."""
    from .models import CompanySettings, SystemSettings
    company = cache.get("company_settings")
    if company is None:
        company = CompanySettings.load()
        cache.set("company_settings", company, 300)
    system = cache.get("system_settings")
    if system is None:
        system = SystemSettings.load()
        cache.set("system_settings", system, 300)
    perms = set()
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        perms = user.effective_permissions()
    return {"company": company, "sys_settings": system, "user_perms": perms}
