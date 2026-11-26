from decimal import Decimal

from django.db import transaction

from core.models import log_action

from .models import StockItem, StockMovement

K = StockMovement.Kind


def move(item, kind, quantity, *, user=None, unit_cost=None, note="", order=None):
    """Change stock by `quantity` (negative removes) and record why. Returns the movement."""
    quantity = Decimal(quantity)
    with transaction.atomic():
        item = StockItem.objects.select_for_update().get(pk=item.pk)
        item.quantity += quantity
        fields = ["quantity"]
        if kind == K.PURCHASE and unit_cost is not None:
            item.unit_cost = Decimal(unit_cost)
            fields.append("unit_cost")
        item.save(update_fields=fields)
        return StockMovement.objects.create(
            item=item, kind=kind, quantity=quantity, unit_cost=unit_cost, balance_after=item.quantity,
            note=note[:200], order=order, user=user if getattr(user, "is_authenticated", False) else None,
        )


def receive(item, quantity, unit_cost, *, user=None, supplier="", record_expense=True, method="CASH", reference=""):
    """Goods received: add stock and (optionally) book the cost as an expense."""
    from finance.models import Expense

    quantity, unit_cost = Decimal(quantity), Decimal(unit_cost)
    with transaction.atomic():
        movement = move(item, K.PURCHASE, quantity, user=user, unit_cost=unit_cost,
                        note=f"From {supplier}" if supplier else "")
        if supplier:
            StockItem.objects.filter(pk=item.pk).update(supplier=supplier[:120])
        if record_expense and quantity * unit_cost > 0:
            category = (Expense.Category.SUPPLIES if item.area in (StockItem.Area.HOUSEKEEPING, StockItem.Area.OTHER)
                        else Expense.Category.FOOD_BEVERAGE)
            Expense.objects.create(
                category=category, amount=(quantity * unit_cost).quantize(Decimal("0.01")),
                description=f"{quantity:g} {item.unit} {item.name}", supplier=supplier[:120], method=method,
                reference=reference[:60], recorded_by=user if getattr(user, "is_authenticated", False) else None,
            )
        log_action(user, "stock.receive", item, f"Received {quantity:g} {item.unit} of {item.name}")
    return movement


def count(item, counted, *, user=None, note=""):
    """Physical stock count: record the difference as a correction."""
    item.refresh_from_db()
    diff = Decimal(counted) - item.quantity
    if diff == 0:
        return None
    return move(item, K.COUNT, diff, user=user, note=note or f"Counted {Decimal(counted):g}")


def deduct_order(order, user=None):
    """Take sold items out of stock once, when the order is paid or charged to a room."""
    from pos.models import Order

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.stock_deducted:
            return 0
        lines = order.items.select_related("menu_item__stock_item")
        moved = 0
        for line in lines:
            menu_item = line.menu_item
            if menu_item and menu_item.stock_item_id and menu_item.stock_item.is_active:
                move(menu_item.stock_item, K.SALE, -(menu_item.stock_quantity * line.quantity), user=user,
                     note=f"{order.number}: {line.quantity} × {line.name}", order=order)
                moved += 1
        Order.objects.filter(pk=order.pk).update(stock_deducted=True)
    return moved


def restore_order(order, user=None):
    """Put stock back when a closed order is cancelled."""
    from pos.models import Order

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if not order.stock_deducted:
            return 0
        sales = StockMovement.objects.filter(order=order, kind=K.SALE).select_related("item")
        for sale in sales:
            move(sale.item, K.RETURN, -sale.quantity, user=user, note=f"{order.number} cancelled", order=order)
        Order.objects.filter(pk=order.pk).update(stock_deducted=False)
        return len(sales)


def low_stock():
    return [i for i in StockItem.objects.filter(is_active=True) if i.is_low]
