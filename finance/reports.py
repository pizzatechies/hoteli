"""Profit and loss: revenue earned (folio charges + direct POS sales) against expenses."""

import datetime
from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from bookings.models import Charge

from .models import Expense

ZERO = Decimal("0.00")


def _bounds(start, end):
    tz = timezone.get_current_timezone()
    return (datetime.datetime.combine(start, datetime.time.min, tzinfo=tz),
            datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz))


def profit_and_loss(start, end):
    from pos.models import Order

    labels = dict(Charge.Category.choices)
    revenue = defaultdict(lambda: ZERO)
    for row in (Charge.objects.filter(is_void=False, service_date__range=(start, end))
                .values("category").annotate(total=Sum("amount"))):
        revenue[labels.get(row["category"], row["category"])] += row["total"] or ZERO
    lo, hi = _bounds(start, end)
    pos_food = pos_drinks = ZERO
    for order in Order.objects.filter(status=Order.Status.PAID, closed_at__gte=lo, closed_at__lt=hi).prefetch_related("items"):
        lines = list(order.items.all())
        subtotal = sum((line.amount for line in lines), ZERO)
        factor = (order.total / subtotal) if subtotal else ZERO  # spread the order discount
        for line in lines:
            if line.kind == "BEVERAGE":
                pos_drinks += line.amount * factor
            else:
                pos_food += line.amount * factor
    if pos_food:
        revenue["Restaurant sales (walk-in)"] += pos_food.quantize(Decimal("0.01"))
    if pos_drinks:
        revenue["Bar sales (walk-in)"] += pos_drinks.quantize(Decimal("0.01"))
    expense_labels = dict(Expense.Category.choices)
    expenses = {expense_labels[r["category"]]: r["total"] for r in
                Expense.objects.filter(date__range=(start, end)).values("category").annotate(total=Sum("amount"))
                .order_by("-total")}
    total_revenue = sum(revenue.values(), ZERO)
    total_expenses = sum(expenses.values(), ZERO)
    profit = total_revenue - total_expenses
    return {
        "revenue": sorted(revenue.items(), key=lambda kv: -kv[1]),
        "expenses": list(expenses.items()),
        "total_revenue": total_revenue,
        "total_expenses": total_expenses,
        "profit": profit,
        "margin": (profit * 100 / total_revenue).quantize(Decimal("0.1")) if total_revenue else ZERO,
    }
