import os

from django.conf import settings
from django.core.exceptions import ValidationError


def _check(value, allowed, kind):
    ext = os.path.splitext(value.name)[1].lower().lstrip(".")
    if ext not in allowed:
        raise ValidationError(
            f"{kind} type '.{ext}' is not allowed. Allowed: {', '.join(allowed)}.")
    limit = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if value.size and value.size > limit:
        raise ValidationError(f"File is larger than {settings.MAX_UPLOAD_SIZE_MB} MB.")


def validate_image_file(value):
    _check(value, settings.ALLOWED_IMAGE_EXTENSIONS, "Image")


def validate_document_file(value):
    _check(value, settings.ALLOWED_DOCUMENT_EXTENSIONS, "Document")


def validate_positive_quantity(value):
    if value is None or value <= 0:
        raise ValidationError("Quantity must be greater than zero.")
