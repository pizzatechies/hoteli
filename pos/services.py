from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from bookings.models import Booking, Charge
from bookings.services import BookingError
from core.models import log_action

from .models import MenuItem, Order, OrderItem

KIND_TO_CATEGORY = {
    MenuItem.Kind.FOOD: Charge.Category.FOOD,
    MenuItem.Kind.BEVERAGE: Charge.Category.BEVERAGE,
    MenuItem.Kind.OTHER: Charge.Category.OTHER,
}


def add_item(order, menu_item, quantity=1, notes=""):
    if not order.is_open:
        raise BookingError("This order is closed.")
    if not menu_item.is_available:
        raise BookingError(f"{menu_item.name} is not available.")
    existing = order.items.filter(menu_item=menu_item, notes=notes, unit_price=menu_item.price).first()
    if existing:
        existing.quantity += quantity
        existing.save(update_fields=["quantity"])
        return existing
    return OrderItem.objects.create(
        order=order, menu_item=menu_item, name=menu_item.name, kind=menu_item.kind,
        quantity=quantity, unit_price=menu_item.price, notes=notes,
    )


def charge_to_room(order, user=None):
    """Post an open order to an in-house guest's folio (split into food / beverage lines)."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if not order.is_open:
            raise BookingError("Only open orders can be charged to a room.")
        if not order.items.exists():
            raise BookingError("Add items to the order first.")
        if order.booking is None or order.booking.status != Booking.Status.CHECKED_IN:
            raise BookingError("Select an in-house (checked-in) guest to charge this order to.")
        if order.paid_total > 0:
            raise BookingError("This order already has payments. Settle the balance instead.")
        totals = {}
        for item in order.items.all():
            category = KIND_TO_CATEGORY.get(item.kind, Charge.Category.OTHER)
            totals[category] = totals.get(category, Decimal("0")) + item.amount
        label = f"{order.get_outlet_display()} {order.number}"
        for category, amount in totals.items():
            Charge.objects.create(
                booking=order.booking, category=category, pos_order=order, posted_by=user,
                description=f"{label} – {Charge.Category(category).label.lower()}",
                unit_price=amount, quantity=1, service_date=timezone.localdate(),
            )
        if order.discount:
            Charge.objects.create(
                booking=order.booking, category=Charge.Category.DISCOUNT, pos_order=order, posted_by=user,
                description=f"{label} – discount", unit_price=min(order.discount, order.subtotal), quantity=1,
            )
        order.status = Order.Status.CHARGED
        order.closed_at = timezone.now()
        order.save(update_fields=["status", "closed_at"])
        from inventory.services import deduct_order

        deduct_order(order, user)
        log_action(user, "pos.charge_room", order,
                   f"{order.number} ({order.total:,.2f}) charged to room {order.booking.room.number}")
    return order


def on_order_payment(order):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status == Order.Status.OPEN and order.total > 0 and order.paid_total >= order.total:
        order.status = Order.Status.PAID
        order.closed_at = timezone.now()
        order.save(update_fields=["status", "closed_at"])
        from inventory.services import deduct_order

        deduct_order(order)


def cancel_order(order, user=None, reason=""):
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status == Order.Status.CHARGED:
            # Reverse the folio postings.
            for charge in order.folio_charges.filter(is_void=False):
                charge.is_void = True
                charge.void_reason = f"POS order cancelled: {reason}"[:200]
                charge.voided_by = user
                charge.voided_at = timezone.now()
                charge.save()
        elif order.status != Order.Status.OPEN:
            raise BookingError("Paid orders cannot be cancelled. Refund or void the payment first.")
        if order.paid_total > 0:
            raise BookingError("Void the payments on this order before cancelling it.")
        from inventory.services import restore_order

        restore_order(order, user)
        order.status = Order.Status.CANCELLED
        order.closed_at = timezone.now()
        order.notes = (f"{order.notes} | Cancelled: {reason}" if order.notes else f"Cancelled: {reason}")[:255]
        order.save(update_fields=["status", "closed_at", "notes"])
        log_action(user, "pos.cancel", order, f"Cancelled {order.number}: {reason}")
    return order
