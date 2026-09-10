"""REST API (sections 37-39).

Authentication: `Authorization: ApiKey <key>`, `X-API-Key`, DRF token, or a
logged-in session. Every unsafe call needs a key with the write scope AND a
user whose role carries the matching permission.

Quantity only - no endpoint accepts or returns a monetary field.
"""
from decimal import Decimal

from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from items.models import Item
from masters.models import (ItemCategory, Location, Rack, RackColumn, RackTable,
                            UnitOfMeasure, Warehouse)
from stock import services
from stock.models import StockBalance, StockMovement
from .permissions import HasAppPermission
from .serializers import (AdjustmentSerializer, CategorySerializer, ColumnSerializer,
                          InwardSerializer, ItemSerializer, ItemSummarySerializer,
                          LocationSerializer, OpeningSerializer, OutwardSerializer,
                          RackSerializer, StockBalanceSerializer, StockMovementSerializer,
                          TableSerializer, TransferSerializer, UnitOfMeasureSerializer,
                          WarehouseSerializer)

ZERO = Decimal("0")


class BaseViewSet(viewsets.ModelViewSet):
    permission_classes = [HasAppPermission]
    throttle_scope = "api"

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class ItemViewSet(BaseViewSet):
    """Item API: GET / POST / PUT / DELETE (disable)."""
    serializer_class = ItemSerializer
    read_permission = "item.view"
    write_permission = "item.change"
    filterset_fields = ["category", "sub_category", "is_active", "manufacturer", "uom"]
    search_fields = ["item_number", "name", "barcode_number", "manufacturer",
                     "model_number", "material", "oem_part_number"]
    ordering_fields = ["item_number", "name", "created_at"]
    lookup_field = "pk"

    def get_queryset(self):
        # Annotated as `stock_total`, not `total_quantity`: the latter is a model
        # property, and an annotation of the same name cannot be assigned onto it.
        qs = Item.objects.select_related("category", "sub_category", "uom").annotate(
            stock_total=Sum("stock_balances__quantity"))
        status_filter = self.request.query_params.get("stock_status")
        if status_filter == "out":
            qs = qs.filter(Q(stock_total__lte=0) | Q(stock_total__isnull=True))
        elif status_filter == "low":
            from django.db.models import F
            qs = qs.filter(stock_total__gt=0, reorder_level__gt=0,
                           stock_total__lte=F("reorder_level"))
        return qs.order_by("item_number")

    def get_serializer_class(self):
        if self.action == "list" and self.request.query_params.get("summary") == "1":
            return ItemSummarySerializer
        return ItemSerializer

    def destroy(self, request, *args, **kwargs):
        """Items are never hard-deleted - they are deactivated, so history survives."""
        item = self.get_object()
        item.is_active = False
        item.save(update_fields=["is_active"])
        return Response({"detail": f"Item {item.item_number} deactivated."},
                        status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], url_path="stock")
    def stock(self, request, pk=None):
        item = self.get_object()
        rows = StockBalance.objects.filter(item=item).select_related("warehouse", "location")
        return Response({
            "item_number": item.item_number,
            "total_quantity": item.total_quantity,
            "available_quantity": item.available_quantity,
            "uom": item.uom.code,
            "stock_status": item.stock_status,
            "locations": StockBalanceSerializer(rows, many=True).data,
        })

    @action(detail=True, methods=["get"], url_path="movements")
    def movements(self, request, pk=None):
        item = self.get_object()
        qs = StockMovement.objects.filter(item=item).select_related(
            "warehouse", "location", "user", "item__uom")[:500]
        return Response(StockMovementSerializer(qs, many=True).data)


class CategoryViewSet(BaseViewSet):
    serializer_class = CategorySerializer
    read_permission = "item.view"
    write_permission = "category.manage"
    filterset_fields = ["parent", "is_active"]
    search_fields = ["name", "code"]

    def get_queryset(self):
        from django.db.models import Count
        return ItemCategory.objects.annotate(item_count=Count("items")).order_by("name")


class WarehouseViewSet(BaseViewSet):
    serializer_class = WarehouseSerializer
    read_permission = "warehouse.view"
    write_permission = "warehouse.manage"
    filterset_fields = ["is_active", "city"]
    search_fields = ["name", "code", "city"]

    def get_queryset(self):
        return Warehouse.objects.order_by("name")

    @action(detail=True, methods=["get"], url_path="stock")
    def stock(self, request, pk=None):
        warehouse = self.get_object()
        rows = (StockBalance.objects.filter(warehouse=warehouse, quantity__gt=0)
                .select_related("item__uom", "location"))
        return Response({
            "warehouse": warehouse.name,
            "total_quantity": rows.aggregate(t=Sum("quantity"))["t"] or ZERO,
            "lines": StockBalanceSerializer(rows, many=True).data,
        })


class LocationViewSet(BaseViewSet):
    serializer_class = LocationSerializer
    read_permission = "location.view"
    write_permission = "location.manage"
    filterset_fields = ["warehouse", "rack", "column", "table", "is_active"]
    search_fields = ["code", "description"]

    def get_queryset(self):
        return Location.objects.select_related("warehouse", "rack", "column",
                                               "table").order_by("code")


class RackViewSet(BaseViewSet):
    serializer_class = RackSerializer
    read_permission = "location.view"
    write_permission = "location.manage"
    filterset_fields = ["warehouse", "is_active"]
    queryset = Rack.objects.all()


class ColumnViewSet(BaseViewSet):
    serializer_class = ColumnSerializer
    read_permission = "location.view"
    write_permission = "location.manage"
    filterset_fields = ["rack", "is_active"]
    queryset = RackColumn.objects.all()


class TableViewSet(BaseViewSet):
    serializer_class = TableSerializer
    read_permission = "location.view"
    write_permission = "location.manage"
    filterset_fields = ["column", "is_active"]
    queryset = RackTable.objects.all()


class UomViewSet(BaseViewSet):
    serializer_class = UnitOfMeasureSerializer
    read_permission = "item.view"
    write_permission = "category.manage"
    queryset = UnitOfMeasure.objects.all()


class StockBalanceViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Read-only current stock. Writes happen through the transaction endpoints."""
    serializer_class = StockBalanceSerializer
    permission_classes = [HasAppPermission]
    read_permission = "stock.view"
    throttle_scope = "api"
    filterset_fields = ["item", "warehouse", "location"]

    def get_queryset(self):
        qs = StockBalance.objects.select_related("item__uom", "warehouse", "location")
        if self.request.query_params.get("hide_zero", "1") == "1":
            qs = qs.filter(quantity__gt=0)
        item_number = self.request.query_params.get("item_number")
        if item_number:
            qs = qs.filter(item__item_number__iexact=item_number)
        return qs.order_by("item__item_number", "location__code")


class MovementViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                      viewsets.GenericViewSet):
    """The stock ledger. Read-only by design - rows are immutable."""
    serializer_class = StockMovementSerializer
    permission_classes = [HasAppPermission]
    read_permission = "stock.view"
    throttle_scope = "api"
    filterset_fields = ["item", "warehouse", "location", "movement_type",
                        "document_type", "document_number"]
    ordering_fields = ["movement_date", "created_at"]

    def get_queryset(self):
        qs = StockMovement.objects.select_related("item__uom", "warehouse", "location",
                                                  "user")
        params = self.request.query_params
        from core.utils import parse_date
        return qs.between(parse_date(params.get("date_from")),
                          parse_date(params.get("date_to")))


# ------------------------------------------------------------- transactions
def _post_document(request, serializer_class, permission_code):
    if not request.user.has_perm_code(permission_code):
        return Response({"detail": "You do not have permission for this operation."},
                        status=status.HTTP_403_FORBIDDEN)
    api_key = getattr(request, "api_key", None)
    if api_key is not None and not api_key.can_write:
        return Response({"detail": "This API key is read-only."},
                        status=status.HTTP_403_FORBIDDEN)
    serializer = serializer_class(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    try:
        doc = serializer.save()
    except services.InsufficientStockError as exc:
        return Response({"detail": str(exc), "code": "insufficient_stock"},
                        status=status.HTTP_409_CONFLICT)
    except services.StockError as exc:
        return Response({"detail": str(exc), "code": "stock_error"},
                        status=status.HTTP_400_BAD_REQUEST)
    return Response({
        "id": doc.pk,
        "document_number": doc.document_number,
        "document_date": doc.document_date,
        "status": doc.status,
        "total_quantity": getattr(doc, "total_quantity", None),
    }, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def post_inward(request):
    return _post_document(request, InwardSerializer, "inward.add")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def post_outward(request):
    return _post_document(request, OutwardSerializer, "outward.add")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def post_transfer(request):
    return _post_document(request, TransferSerializer, "transfer.add")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def post_adjustment(request):
    return _post_document(request, AdjustmentSerializer, "adjustment.add")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def post_opening(request):
    return _post_document(request, OpeningSerializer, "opening.add")


# ------------------------------------------------------------ barcode / QR
@api_view(["GET"])
@permission_classes([IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
def item_by_barcode(request, code):
    """Barcode API - what a hardware scanner calls."""
    item = Item.objects.filter(
        Q(barcode_number__iexact=code) | Q(item_number__iexact=code)
    ).select_related("category", "uom").first()
    if item is None:
        return Response({"detail": "Barcode not registered.", "code": "not_found"},
                        status=status.HTTP_404_NOT_FOUND)
    return Response(ItemSerializer(item, context={"request": request}).data)


item_by_barcode.throttle_scope = "scan"


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def item_by_qr(request, token):
    """QR API - resolves the opaque token printed on the label."""
    item = get_object_or_404(Item.objects.select_related("category", "uom"),
                             qr_token=token)
    return Response(ItemSerializer(item, context={"request": request}).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_root(request):
    from django.urls import reverse
    base = request.build_absolute_uri("/api/v1/")
    return Response({
        "items": base + "items/",
        "item_stock": base + "items/{id}/stock/",
        "item_movements": base + "items/{id}/movements/",
        "categories": base + "categories/",
        "warehouses": base + "warehouses/",
        "warehouse_stock": base + "warehouses/{id}/stock/",
        "locations": base + "locations/",
        "racks": base + "racks/",
        "columns": base + "columns/",
        "tables": base + "tables/",
        "uom": base + "uom/",
        "stock": base + "stock/",
        "movements": base + "movements/",
        "inward": base + "stock/inward/",
        "outward": base + "stock/outward/",
        "transfer": base + "stock/transfer/",
        "adjustment": base + "stock/adjustment/",
        "opening": base + "stock/opening/",
        "by_barcode": base + "barcode/{code}/",
        "by_qr": base + "qr/{token}/",
        "note": "Quantity-only inventory API. No price, cost, tax or value fields exist.",
    })
