"""Aggregations for the dashboard and management reports."""

import datetime
from collections import Counter, defaultdict
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from bookings.models import ZERO, Booking, Charge, Payment, signed_payment_sum
from rooms.models import Room


def _days(start, end):
    day = start
    while day <= end:
        yield day
        day += datetime.timedelta(days=1)


def _aware_range(start, end):
    """Datetime bounds covering local dates [start, end]."""
    tz = timezone.get_current_timezone()
    lo = datetime.datetime.combine(start, datetime.time.min, tzinfo=tz)
    hi = datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz)
    return lo, hi


def payments_in_range(start, end):
    lo, hi = _aware_range(start, end)
    return Payment.objects.filter(is_void=False, created_at__gte=lo, created_at__lt=hi)


def occupancy_counts(start, end, statuses=(Booking.Status.CHECKED_IN, Booking.Status.CHECKED_OUT)):
    counts = Counter()
    qs = Booking.objects.filter(
        status__in=statuses, check_in_date__lte=end, check_out_date__gt=start
    ).values_list("check_in_date", "check_out_date")
    for ci, co in qs:
        day = max(ci, start)
        last = min(co - datetime.timedelta(days=1), end)
        while day <= last:
            counts[day] += 1
            day += datetime.timedelta(days=1)
    return counts


def daily_stats(start, end):
    rooms_available = Room.objects.filter(is_active=True).count()
    occ = occupancy_counts(start, end)
    room_rev = dict(
        Charge.objects.filter(is_void=False, category=Charge.Category.ROOM, service_date__range=(start, end))
        .values("service_date").annotate(t=Sum("amount")).values_list("service_date", "t")
    )
    other_rev = dict(
        Charge.objects.filter(is_void=False, service_date__range=(start, end))
        .exclude(category=Charge.Category.ROOM)
        .values("service_date").annotate(t=Sum("amount")).values_list("service_date", "t")
    )
    collected = dict(
        payments_in_range(start, end).annotate(d=TruncDate("created_at"))
        .values("d").annotate(t=Sum(signed_payment_sum())).values_list("d", "t")
    )
    rows = []
    totals = defaultdict(lambda: ZERO)
    total_sold = 0
    for day in _days(start, end):
        sold = occ.get(day, 0)
        rr = room_rev.get(day) or ZERO
        orv = other_rev.get(day) or ZERO
        col = collected.get(day) or ZERO
        rows.append({
            "date": day,
            "rooms_sold": sold,
            "occupancy": (Decimal(sold) * 100 / rooms_available).quantize(Decimal("0.1")) if rooms_available else ZERO,
            "room_revenue": rr,
            "other_revenue": orv,
            "total_revenue": rr + orv,
            "adr": (rr / sold).quantize(Decimal("0.01")) if sold else ZERO,
            "revpar": (rr / rooms_available).quantize(Decimal("0.01")) if rooms_available else ZERO,
            "collected": col,
        })
        total_sold += sold
        totals["room_revenue"] += rr
        totals["other_revenue"] += orv
        totals["collected"] += col
    n_days = len(rows) or 1
    summary = {
        "rooms_available": rooms_available,
        "room_nights_sold": total_sold,
        "occupancy": (Decimal(total_sold) * 100 / (rooms_available * n_days)).quantize(Decimal("0.1"))
        if rooms_available else ZERO,
        "room_revenue": totals["room_revenue"],
        "other_revenue": totals["other_revenue"],
        "total_revenue": totals["room_revenue"] + totals["other_revenue"],
        "collected": totals["collected"],
        "adr": (totals["room_revenue"] / total_sold).quantize(Decimal("0.01")) if total_sold else ZERO,
        "revpar": (totals["room_revenue"] / (rooms_available * n_days)).quantize(Decimal("0.01"))
        if rooms_available else ZERO,
    }
    return rows, summary


def revenue_by_category(start, end):
    rows = (
        Charge.objects.filter(is_void=False, service_date__range=(start, end))
        .values("category").annotate(total=Sum("amount"), count=Count("id")).order_by("-total")
    )
    labels = dict(Charge.Category.choices)
    return [{"label": labels.get(r["category"], r["category"]), **r} for r in rows]


def payments_by_method(start, end):
    rows = (
        payments_in_range(start, end).values("method", "kind")
        .annotate(total=Sum("amount"), count=Count("id")).order_by("method", "kind")
    )
    labels = dict(Payment.Method.choices)
    summary = defaultdict(lambda: {"payments": ZERO, "refunds": ZERO, "count": 0})
    for r in rows:
        entry = summary[r["method"]]
        entry["label"] = labels.get(r["method"], r["method"])
        entry["count"] += r["count"]
        if r["kind"] == Payment.Kind.REFUND:
            entry["refunds"] += r["total"]
        else:
            entry["payments"] += r["total"]
    result = []
    for method, entry in summary.items():
        entry["net"] = entry["payments"] - entry["refunds"]
        entry["method"] = method
        result.append(entry)
    return sorted(result, key=lambda e: -e["net"])


def outstanding_balances():
    """Bookings that still owe money (in-house running balances and departed guests' receivables)."""
    qs = (
        Booking.objects.with_totals()
        .filter(status__in=(Booking.Status.CHECKED_IN, Booking.Status.CHECKED_OUT))
        .select_related("guest", "room")
    )
    return [b for b in qs if b.balance > 0]


def credit_balances():
    """Bookings where the guest paid more than was charged (refund or carry forward)."""
    qs = (
        Booking.objects.with_totals()
        .filter(status__in=(Booking.Status.CHECKED_OUT, Booking.Status.CANCELLED, Booking.Status.NO_SHOW))
        .select_related("guest", "room")
    )
    return [b for b in qs if b.balance < 0]
