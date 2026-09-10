from django import template
from django.utils.http import urlencode

register = template.Library()


@register.filter
def dict_get(mapping, key):
    """Look up a dict value by key: {{ item.custom_fields|dict_get:cf.key }}"""
    if not mapping:
        return ""
    try:
        return mapping.get(key, "")
    except AttributeError:
        return ""


@register.filter
def index(sequence, position):
    try:
        return sequence[position]
    except (IndexError, TypeError, KeyError):
        return ""


@register.filter
def has_perm(user_perms, code):
    return code in (user_perms or set())


@register.simple_tag(takes_context=True)
def query_replace(context, **kwargs):
    """Rebuild the query string with some parameters replaced."""
    params = context["request"].GET.copy()
    for key, value in kwargs.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = value
    params.pop("page", None)
    return params.urlencode()


@register.filter
def qty(value, places=2):
    """Trim trailing zeros from a quantity for display."""
    if value in (None, ""):
        return "0"
    try:
        text = f"{float(value):,.{places}f}"
    except (TypeError, ValueError):
        return value
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


@register.filter
def cell_class(index, numeric):
    return "num" if index in (numeric or set()) else ""
