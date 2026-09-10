"""Static file storage that fails soft.

Django's manifest storage raises `ValueError: Missing staticfiles manifest entry`
whenever a template asks for a file that `collectstatic` has not hashed. That
turns one missing asset - or a `collectstatic` run that was skipped, or run with
different settings than the server - into a 500 on **every page**, including the
login screen, with a message that means nothing to the person deploying it.

On shared hosting that ordering mistake is easy to make, so a missing entry falls
back to the plain filename here. Worst case a stylesheet 404s and the page looks
unstyled; the application still works and the cause is obvious.
"""
from whitenoise.storage import CompressedManifestStaticFilesStorage


class ForgivingManifestStaticFilesStorage(CompressedManifestStaticFilesStorage):
    # Serve the unhashed path instead of raising when an entry is absent.
    manifest_strict = False
