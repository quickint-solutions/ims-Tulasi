"""REST serializers. QUANTITY ONLY - no price, rate, amount or tax field exists."""
from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from items.models import Item, ItemDocument, ItemImage
from masters.models import (ItemCategory, Location, Rack, RackColumn, RackTable,
                            UnitOfMeasure, Warehouse)
from stock import services
from stock.models import (AdjustmentDocument, AdjustmentItem, InwardDocument, InwardItem,
                          OpeningStockDocument, OpeningStockItem, OutwardDocument,
                          OutwardItem, StockBalance, StockMovement, TransferDocument,
                          TransferItem)


class UnitOfMeasureSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnitOfMeasure
        fields = ["id", "code", "name", "decimal_places", "is_active"]


class CategorySerializer(serializers.ModelSerializer):
    parent_name = serializers.CharField(source="parent.name", read_only=True)
    item_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ItemCategory
        fields = ["id", "code", "name", "parent", "parent_name", "description",
                  "is_active", "item_count"]


class WarehouseSerializer(serializers.ModelSerializer):
    total_quantity = serializers.SerializerMethodField()

    class Meta:
        model = Warehouse
        fields = ["id", "code", "name", "address", "city", "contact_person",
                  "contact_number", "remarks", "is_active", "total_quantity"]

    def get_total_quantity(self, obj):
        from django.db.models import Sum
        return obj.stock_balances.aggregate(t=Sum("quantity"))["t"] or Decimal("0")


class LocationSerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    rack_code = serializers.CharField(read_only=True)
    column_code = serializers.CharField(read_only=True)
    table_code = serializers.CharField(read_only=True)

    class Meta:
        model = Location
        fields = ["id", "code", "warehouse", "warehouse_name", "rack", "rack_code",
                  "column", "column_code", "table", "table_code", "description",
                  "is_default", "is_active"]
        read_only_fields = ["code"]


class RackSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rack
        fields = ["id", "warehouse", "code", "name", "description", "is_active"]


class ColumnSerializer(serializers.ModelSerializer):
    class Meta:
        model = RackColumn
        fields = ["id", "rack", "code", "name", "description", "is_active"]


class TableSerializer(serializers.ModelSerializer):
    class Meta:
        model = RackTable
        fields = ["id", "column", "code", "name", "description", "is_active"]


class ItemImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemImage
        fields = ["id", "image", "caption", "sort_order"]


class ItemDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemDocument
        fields = ["id", "file", "doc_type", "title", "is_public"]


class StockByLocationSerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)
    rack = serializers.CharField(source="location.rack_code", read_only=True)
    column = serializers.CharField(source="location.column_code", read_only=True)
    table = serializers.CharField(source="location.table_code", read_only=True)
    available_quantity = serializers.DecimalField(max_digits=18, decimal_places=3,
                                                  read_only=True)

    class Meta:
        model = StockBalance
        fields = ["warehouse", "warehouse_name", "location", "location_code",
                  "rack", "column", "table", "quantity", "reserved_quantity",
                  "available_quantity"]


class _TotalQuantityMixin:
    def get_total_quantity(self, obj):
        """Prefer the queryset annotation; fall back to the model property."""
        annotated = getattr(obj, "stock_total", None)
        return annotated if annotated is not None else obj.total_quantity


class ItemSerializer(_TotalQuantityMixin, serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    uom_code = serializers.CharField(source="uom.code", read_only=True)
    total_quantity = serializers.SerializerMethodField()
    stock_status = serializers.CharField(read_only=True)
    qr_url = serializers.SerializerMethodField()
    stock_by_location = StockByLocationSerializer(source="stock_balances", many=True,
                                                  read_only=True)
    images = ItemImageSerializer(many=True, read_only=True)

    class Meta:
        model = Item
        fields = [
            "id", "item_number", "name", "category", "category_name", "sub_category",
            "description", "manufacturer", "model_number", "drawing_number",
            "oem_part_number", "alternate_part_number", "material", "material_grade",
            "weight", "weight_unit", "length", "width", "height", "dimension_unit",
            "size", "size_unit", "colour", "spare_type", "application", "specification",
            "uom", "uom_code", "minimum_stock", "maximum_stock", "reorder_level",
            "barcode_number", "qr_url", "image", "images", "default_location",
            "custom_fields", "remarks", "is_active",
            "total_quantity", "stock_status", "stock_by_location",
        ]
        read_only_fields = ["qr_token"]

    def get_qr_url(self, obj):
        request = self.context.get("request")
        return obj.public_url(request)


class ItemSummarySerializer(_TotalQuantityMixin, serializers.ModelSerializer):
    uom_code = serializers.CharField(source="uom.code", read_only=True)
    total_quantity = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = ["id", "item_number", "name", "category", "uom_code", "barcode_number",
                  "total_quantity", "is_active"]


class StockMovementSerializer(serializers.ModelSerializer):
    item_number = serializers.CharField(source="item.item_number", read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)
    uom = serializers.CharField(source="item.uom.code", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)
    signed_quantity = serializers.DecimalField(max_digits=18, decimal_places=3,
                                               read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = StockMovement
        fields = ["id", "movement_date", "created_at", "movement_type", "direction",
                  "item", "item_number", "item_name", "uom", "quantity",
                  "signed_quantity", "balance_after", "warehouse", "warehouse_name",
                  "location", "location_code", "document_type", "document_number",
                  "reference", "party", "remarks", "username", "is_reversal"]


class StockBalanceSerializer(serializers.ModelSerializer):
    item_number = serializers.CharField(source="item.item_number", read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)
    uom = serializers.CharField(source="item.uom.code", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)
    available_quantity = serializers.DecimalField(max_digits=18, decimal_places=3,
                                                  read_only=True)

    class Meta:
        model = StockBalance
        fields = ["item", "item_number", "item_name", "uom", "warehouse", "warehouse_name",
                  "location", "location_code", "quantity", "reserved_quantity",
                  "available_quantity", "last_movement_at"]


# --------------------------------------------------------------- transactions
class _LineSerializer(serializers.Serializer):
    item = serializers.CharField(help_text="Item number or numeric id.")
    location = serializers.CharField(help_text="Location code or numeric id.")
    quantity = serializers.DecimalField(max_digits=18, decimal_places=3,
                                        min_value=Decimal("0.001"))
    remarks = serializers.CharField(required=False, allow_blank=True, max_length=255)

    def validate_item(self, value):
        obj = (Item.objects.filter(pk=value).first() if str(value).isdigit()
               else Item.objects.filter(item_number__iexact=value).first())
        if obj is None:
            obj = Item.objects.filter(barcode_number__iexact=value).first()
        if obj is None:
            raise serializers.ValidationError(f"Item '{value}' not found.")
        return obj

    def validate_location(self, value):
        obj = (Location.objects.filter(pk=value).first() if str(value).isdigit()
               else Location.objects.filter(code__iexact=value).first())
        if obj is None:
            raise serializers.ValidationError(f"Location '{value}' not found.")
        return obj


class TransferLineSerializer(_LineSerializer):
    location = None
    from_location = serializers.CharField()
    to_location = serializers.CharField()

    def validate_from_location(self, value):
        return _LineSerializer.validate_location(self, value)

    def validate_to_location(self, value):
        return _LineSerializer.validate_location(self, value)


class AdjustmentLineSerializer(_LineSerializer):
    quantity = None
    physical_quantity = serializers.DecimalField(max_digits=18, decimal_places=3,
                                                 min_value=Decimal("0"))
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


class _DocumentSerializer(serializers.Serializer):
    """Manual document numbers - the API never invents one (section 35)."""
    document_number = serializers.CharField(max_length=64)
    document_date = serializers.DateField(required=False)
    reference_number = serializers.CharField(required=False, allow_blank=True, max_length=64)
    remarks = serializers.CharField(required=False, allow_blank=True)
    post = serializers.BooleanField(
        default=True, help_text="Post immediately. False leaves the document as a draft.")

    model = None
    line_model = None
    line_serializer = _LineSerializer

    def validate_document_number(self, value):
        value = value.strip().upper()
        if self.model.objects.filter(document_number=value).exists():
            raise serializers.ValidationError(
                f"Document number {value} already exists.")
        return value

    def _resolve_warehouse(self, value):
        obj = (Warehouse.objects.filter(pk=value).first() if str(value).isdigit()
               else Warehouse.objects.filter(code__iexact=value).first()
               or Warehouse.objects.filter(name__iexact=value).first())
        if obj is None:
            raise serializers.ValidationError({"warehouse": f"Warehouse '{value}' not found."})
        return obj


class InwardSerializer(_DocumentSerializer):
    model = InwardDocument
    line_model = InwardItem
    warehouse = serializers.CharField(help_text="Warehouse code, name or id.")
    supplier = serializers.CharField(required=False, allow_blank=True, max_length=150)
    lines = _LineSerializer(many=True)

    @transaction.atomic
    def create(self, validated):
        lines = validated.pop("lines")
        should_post = validated.pop("post", True)
        warehouse = self._resolve_warehouse(validated.pop("warehouse"))
        user = self.context["request"].user
        doc = InwardDocument.objects.create(warehouse=warehouse, created_by=user, **validated)
        for line in lines:
            InwardItem.objects.create(document=doc, item=line["item"],
                                      location=line["location"], quantity=line["quantity"],
                                      remarks=line.get("remarks", ""))
        if should_post:
            services.post_document(doc, user=user)
        return doc


class OutwardSerializer(_DocumentSerializer):
    model = OutwardDocument
    line_model = OutwardItem
    warehouse = serializers.CharField()
    destination = serializers.CharField(required=False, allow_blank=True, max_length=150)
    allow_negative = serializers.BooleanField(default=False)
    lines = _LineSerializer(many=True)

    @transaction.atomic
    def create(self, validated):
        lines = validated.pop("lines")
        should_post = validated.pop("post", True)
        warehouse = self._resolve_warehouse(validated.pop("warehouse"))
        user = self.context["request"].user
        doc = OutwardDocument.objects.create(warehouse=warehouse, created_by=user, **validated)
        for line in lines:
            OutwardItem.objects.create(document=doc, item=line["item"],
                                       location=line["location"], quantity=line["quantity"],
                                       remarks=line.get("remarks", ""))
        if should_post:
            services.post_document(doc, user=user)
        return doc


class TransferSerializer(_DocumentSerializer):
    model = TransferDocument
    line_model = TransferItem
    from_warehouse = serializers.CharField()
    to_warehouse = serializers.CharField()
    allow_negative = serializers.BooleanField(default=False)
    lines = TransferLineSerializer(many=True)

    @transaction.atomic
    def create(self, validated):
        lines = validated.pop("lines")
        should_post = validated.pop("post", True)
        src = self._resolve_warehouse(validated.pop("from_warehouse"))
        dst = self._resolve_warehouse(validated.pop("to_warehouse"))
        user = self.context["request"].user
        doc = TransferDocument.objects.create(from_warehouse=src, to_warehouse=dst,
                                              created_by=user, **validated)
        for line in lines:
            TransferItem.objects.create(document=doc, item=line["item"],
                                        from_location=line["from_location"],
                                        to_location=line["to_location"],
                                        quantity=line["quantity"],
                                        remarks=line.get("remarks", ""))
        if should_post:
            services.post_document(doc, user=user)
        return doc


class AdjustmentSerializer(_DocumentSerializer):
    model = AdjustmentDocument
    line_model = AdjustmentItem
    warehouse = serializers.CharField()
    reason = serializers.ChoiceField(choices=AdjustmentDocument.Reason.choices,
                                     default=AdjustmentDocument.Reason.PHYSICAL_COUNT)
    lines = AdjustmentLineSerializer(many=True)

    @transaction.atomic
    def create(self, validated):
        lines = validated.pop("lines")
        should_post = validated.pop("post", True)
        warehouse = self._resolve_warehouse(validated.pop("warehouse"))
        user = self.context["request"].user
        doc = AdjustmentDocument.objects.create(warehouse=warehouse, created_by=user,
                                                **validated)
        for line in lines:
            AdjustmentItem.objects.create(
                document=doc, item=line["item"], location=line["location"],
                physical_quantity=line["physical_quantity"],
                reason=line.get("reason", ""), remarks=line.get("remarks", ""))
        if should_post:
            services.post_document(doc, user=user)
        return doc


class OpeningSerializer(_DocumentSerializer):
    model = OpeningStockDocument
    line_model = OpeningStockItem
    warehouse = serializers.CharField()
    lines = _LineSerializer(many=True)

    @transaction.atomic
    def create(self, validated):
        lines = validated.pop("lines")
        should_post = validated.pop("post", True)
        warehouse = self._resolve_warehouse(validated.pop("warehouse"))
        user = self.context["request"].user
        doc = OpeningStockDocument.objects.create(warehouse=warehouse, created_by=user,
                                                  **validated)
        for line in lines:
            OpeningStockItem.objects.create(document=doc, item=line["item"],
                                            location=line["location"],
                                            quantity=line["quantity"],
                                            remarks=line.get("remarks", ""))
        if should_post:
            services.post_document(doc, user=user)
        return doc


class DocumentResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    document_number = serializers.CharField()
    document_date = serializers.DateField()
    status = serializers.CharField()
    total_quantity = serializers.DecimalField(max_digits=18, decimal_places=3,
                                              required=False)
