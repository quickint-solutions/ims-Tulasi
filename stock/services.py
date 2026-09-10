"""Stock posting engine.

Every stock change in the system goes through post_document(). Nothing else
may write StockBalance. Quantities only - this module has no concept of money.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from accounts import audit
from .models import (
    AdjustmentDocument, DocumentStatus, InwardDocument, MovementType,
    OpeningStockDocument, OutwardDocument, StockBalance, StockMovement,
    TransferDocument,
)

ZERO = Decimal("0")


class StockError(Exception):
    """Base class for stock posting failures shown to the user."""


class InsufficientStockError(StockError):
    def __init__(self, item, location, available, requested):
        self.item, self.location = item, location
        self.available, self.requested = available, requested
        super().__init__(
            f"Insufficient stock: {item.item_number} at {location.code} has "
            f"{available:g} {item.uom.code}, tried to issue {requested:g}.")


class DocumentStateError(StockError):
    pass


# --------------------------------------------------------------------------
# Low level
# --------------------------------------------------------------------------
def _lock_balance(item, location):
    balance, _created = StockBalance.objects.select_for_update().get_or_create(
        item=item, location=location,
        defaults={"warehouse_id": location.warehouse_id, "quantity": ZERO},
    )
    return balance


def apply_movement(*, item, location, quantity, direction, movement_type, movement_date,
                   document_type="", document_number="", document_id=None, line_id=None,
                   reference="", party="", remarks="", user=None, allow_negative=False,
                   is_reversal=False, reverses=None):
    """Write one ledger row and move the balance. Must run inside a transaction."""
    quantity = Decimal(quantity)
    if quantity <= 0:
        raise StockError("Quantity must be greater than zero.")

    balance = _lock_balance(item, location)
    if direction < 0 and not allow_negative:
        if balance.quantity - quantity < 0:
            raise InsufficientStockError(item, location, balance.quantity, quantity)

    new_qty = balance.quantity + (quantity * direction)
    StockBalance.objects.filter(pk=balance.pk).update(
        quantity=F("quantity") + (quantity * direction),
        last_movement_at=timezone.now(),
    )
    return StockMovement.objects.create(
        movement_date=movement_date,
        movement_type=movement_type,
        direction=direction,
        item=item,
        warehouse_id=location.warehouse_id,
        location=location,
        quantity=quantity,
        balance_after=new_qty,
        document_type=document_type,
        document_number=document_number,
        document_id=document_id,
        line_id=line_id,
        reference=reference,
        party=party,
        remarks=remarks,
        user=user,
        is_reversal=is_reversal,
        reverses=reverses,
    )


# --------------------------------------------------------------------------
# Per-document posting plans
# --------------------------------------------------------------------------
def _plan_inward(doc):
    for line in doc.lines.select_related("item", "location"):
        yield dict(item=line.item, location=line.location, quantity=line.quantity,
                   direction=1, movement_type=MovementType.INWARD, line_id=line.pk,
                   party=doc.supplier, remarks=line.remarks)


def _plan_outward(doc):
    for line in doc.lines.select_related("item", "location"):
        yield dict(item=line.item, location=line.location, quantity=line.quantity,
                   direction=-1, movement_type=MovementType.OUTWARD, line_id=line.pk,
                   party=doc.destination, remarks=line.remarks)


def _plan_transfer(doc):
    for line in doc.lines.select_related("item", "from_location", "to_location"):
        yield dict(item=line.item, location=line.from_location, quantity=line.quantity,
                   direction=-1, movement_type=MovementType.TRANSFER_OUT, line_id=line.pk,
                   party=str(line.to_location), remarks=line.remarks)
        yield dict(item=line.item, location=line.to_location, quantity=line.quantity,
                   direction=1, movement_type=MovementType.TRANSFER_IN, line_id=line.pk,
                   party=str(line.from_location), remarks=line.remarks)


def _plan_adjustment(doc):
    for line in doc.lines.select_related("item", "location"):
        diff = line.difference
        if diff == 0:
            continue
        yield dict(item=line.item, location=line.location, quantity=abs(diff),
                   direction=1 if diff > 0 else -1, movement_type=MovementType.ADJUSTMENT,
                   line_id=line.pk, party=doc.get_reason_display(),
                   remarks=line.reason or line.remarks)


def _plan_opening(doc):
    for line in doc.lines.select_related("item", "location"):
        yield dict(item=line.item, location=line.location, quantity=line.quantity,
                   direction=1, movement_type=MovementType.OPENING, line_id=line.pk,
                   remarks=line.remarks)


PLANNERS = {
    InwardDocument: ("INWARD", _plan_inward, audit.AuditLog.Action.INWARD),
    OutwardDocument: ("OUTWARD", _plan_outward, audit.AuditLog.Action.OUTWARD),
    TransferDocument: ("TRANSFER", _plan_transfer, audit.AuditLog.Action.TRANSFER),
    AdjustmentDocument: ("ADJUSTMENT", _plan_adjustment, audit.AuditLog.Action.ADJUSTMENT),
    OpeningStockDocument: ("OPENING", _plan_opening, audit.AuditLog.Action.OPENING),
}


def _planner_for(doc):
    for klass, spec in PLANNERS.items():
        if isinstance(doc, klass):
            return spec
    raise StockError(f"Unsupported document type: {doc.__class__.__name__}")


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
@transaction.atomic
def post_document(doc, user=None):
    """Validate and post a draft document, writing all ledger rows atomically."""
    if doc.status == DocumentStatus.POSTED:
        raise DocumentStateError(f"{doc.document_number} is already posted.")
    if doc.status == DocumentStatus.CANCELLED:
        raise DocumentStateError(f"{doc.document_number} is cancelled and cannot be posted.")

    doc_type, planner, action = _planner_for(doc)
    plan = list(planner(doc))
    if not plan:
        raise StockError("Add at least one line with a quantity before posting.")

    allow_negative = bool(getattr(doc, "allow_negative", False))
    if allow_negative and user is not None and not user.has_perm_code("stock.negative_override"):
        raise StockError("You are not permitted to post stock below zero.")

    # Adjustments re-snapshot system quantity at posting time so the recorded
    # difference matches what actually moved.
    if isinstance(doc, AdjustmentDocument):
        for line in doc.lines.select_related("item", "location"):
            line.system_quantity = StockBalance.objects.filter(
                item=line.item, location=line.location).values_list(
                "quantity", flat=True).first() or ZERO
            line.save(update_fields=["system_quantity"])
        plan = list(planner(doc))

    total = ZERO
    for step in plan:
        apply_movement(
            movement_date=doc.document_date,
            document_type=doc_type,
            document_number=doc.document_number,
            document_id=doc.pk,
            reference=doc.reference_number,
            user=user,
            allow_negative=allow_negative,
            **step,
        )
        total += step["quantity"]

    doc.status = DocumentStatus.POSTED
    doc.posted_at = timezone.now()
    doc.posted_by = user
    doc.save(update_fields=["status", "posted_at", "posted_by", "updated_at"])

    audit.log(action, user=user, obj=doc, document_number=doc.document_number,
              quantity=total, description=f"Posted {doc_type} {doc.document_number}")
    return doc


@transaction.atomic
def cancel_document(doc, user=None, reason=""):
    """Reverse a posted document. Original rows are kept; contra rows are added."""
    if doc.status != DocumentStatus.POSTED:
        raise DocumentStateError("Only a posted document can be reversed.")

    doc_type, _planner, _action = _planner_for(doc)
    originals = StockMovement.objects.filter(
        document_type=doc_type, document_id=doc.pk, is_reversal=False
    ).select_related("item", "location")
    if not originals.exists():
        raise StockError("No ledger rows found for this document.")

    for mv in originals:
        apply_movement(
            item=mv.item, location=mv.location, quantity=mv.quantity,
            direction=-mv.direction, movement_type=MovementType.CORRECTION,
            movement_date=timezone.localdate(), document_type=doc_type,
            document_number=doc.document_number, document_id=doc.pk, line_id=mv.line_id,
            reference=doc.reference_number, party=mv.party,
            remarks=(reason or "Document reversed")[:255], user=user,
            allow_negative=True, is_reversal=True, reverses=mv,
        )

    doc.status = DocumentStatus.CANCELLED
    doc.cancelled_at = timezone.now()
    doc.cancelled_by = user
    doc.cancel_reason = reason[:255]
    doc.save(update_fields=["status", "cancelled_at", "cancelled_by", "cancel_reason",
                            "updated_at"])
    audit.log(audit.AuditLog.Action.REVERSAL, user=user, obj=doc,
              document_number=doc.document_number,
              description=f"Reversed {doc_type} {doc.document_number}: {reason}")
    return doc


def check_availability(item, location, quantity):
    """Return (ok, available) without locking - for UI pre-validation."""
    available = StockBalance.available_at(item, location)
    return available >= Decimal(quantity), available


@transaction.atomic
def recalculate_balances(item=None):
    """Rebuild StockBalance from the ledger. Reconciliation / repair tool."""
    movements = StockMovement.objects.all()
    balances = StockBalance.objects.all()
    if item is not None:
        movements = movements.filter(item=item)
        balances = balances.filter(item=item)

    totals = {}
    for row in movements.values("item_id", "location_id").annotate(
            qty=Sum(F("quantity") * F("direction"))):
        totals[(row["item_id"], row["location_id"])] = row["qty"] or ZERO

    updated = 0
    for bal in balances.select_for_update():
        expected = totals.pop((bal.item_id, bal.location_id), ZERO)
        if bal.quantity != expected:
            bal.quantity = expected
            bal.save(update_fields=["quantity"])
            updated += 1
    from masters.models import Location
    for (item_id, location_id), qty in totals.items():
        loc = Location.objects.get(pk=location_id)
        StockBalance.objects.create(item_id=item_id, location_id=location_id,
                                    warehouse_id=loc.warehouse_id, quantity=qty)
        updated += 1
    return updated
