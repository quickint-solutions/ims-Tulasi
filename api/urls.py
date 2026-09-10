from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "api"

router = DefaultRouter()
router.register("items", views.ItemViewSet, basename="item")
router.register("categories", views.CategoryViewSet, basename="category")
router.register("warehouses", views.WarehouseViewSet, basename="warehouse")
router.register("locations", views.LocationViewSet, basename="location")
router.register("racks", views.RackViewSet, basename="rack")
router.register("columns", views.ColumnViewSet, basename="column")
router.register("tables", views.TableViewSet, basename="table")
router.register("uom", views.UomViewSet, basename="uom")
router.register("stock", views.StockBalanceViewSet, basename="stock")
router.register("movements", views.MovementViewSet, basename="movement")

urlpatterns = [
    path("", views.api_root, name="root"),
    path("stock/inward/", views.post_inward, name="post_inward"),
    path("stock/outward/", views.post_outward, name="post_outward"),
    path("stock/transfer/", views.post_transfer, name="post_transfer"),
    path("stock/adjustment/", views.post_adjustment, name="post_adjustment"),
    path("stock/opening/", views.post_opening, name="post_opening"),
    path("barcode/<str:code>/", views.item_by_barcode, name="by_barcode"),
    path("qr/<str:token>/", views.item_by_qr, name="by_qr"),
    path("", include(router.urls)),
]
