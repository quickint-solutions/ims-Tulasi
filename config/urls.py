from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path

from items.views import public_item

urlpatterns = [
    path("", include("core.urls")),
    path("accounts/", include("accounts.urls")),
    path("items/", include("items.urls")),
    path("masters/", include("masters.urls")),
    path("stock/", include("stock.urls")),
    path("barcode/", include("labels.urls")),
    path("reports/", include("reports.urls")),
    path("integration/", include("integration.urls")),
    path("api/v1/", include("api.urls")),

    # Public, token-addressed item page opened by scanning the label QR code.
    path("i/<str:token>/", public_item, name="public_item"),

    path("django-admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
elif settings.SERVE_MEDIA:
    # Product images, documents and the company logo. django.conf.urls.static.static()
    # is a no-op outside DEBUG, so the view is wired up explicitly - without this an
    # on-premise install running with DEBUG=0 returns 404 for every uploaded file.
    from django.views.static import serve as serve_media

    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", serve_media,
                {"document_root": settings.MEDIA_ROOT}),
    ]
