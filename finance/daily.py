"""Morning summary email for managers."""

import datetime
import logging
from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import Sum
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger("bookings")


def build_report(day=None):
    from bookings.models import Booking
    from channel_sync.models import RoomBlock
    from core import reports
    from core.models import HotelSettings
    from housekeeping.models import MaintenanceRequest
    from inventory.services import low_stock
    from mpesa.models import C2BTransaction
    from notifications.models import SmsMessage

    from .models import Expense

    day = day or (timezone.localdate() - datetime.timedelta(days=1))
    today = day + datetime.timedelta(days=1)
    rows, summary = reports.daily_stats(day, day)
    outstanding = reports.outstanding_balances()
    return {
        "hotel": HotelSettings.load(),
        "day": day,
        "today": today,
        "stats": rows[0] if rows else {},
        "summary": summary,
        "by_method": reports.payments_by_method(day, day),
        "expenses": Expense.objects.filter(date=day).aggregate(t=Sum("amount"))["t"] or Decimal("0"),
        "arrivals": Booking.objects.filter(status__in=(Booking.Status.PENDING, Booking.Status.CONFIRMED),
                                           check_in_date=today).select_related("guest", "room"),
        "departures": Booking.objects.filter(status=Booking.Status.CHECKED_IN, check_out_date__lte=today)
        .select_related("guest", "room"),
        "in_house": Booking.objects.filter(status=Booking.Status.CHECKED_IN).count(),
        "outstanding_total": sum((b.balance for b in outstanding), Decimal("0")),
        "outstanding_count": len(outstanding),
        "low_stock": low_stock(),
        "open_maintenance": MaintenanceRequest.objects.filter(status__in=MaintenanceRequest.OPEN_STATUSES).count(),
        "unmatched_paybill": C2BTransaction.objects.filter(status=C2BTransaction.Status.UNMATCHED).count(),
        "ota_conflicts": RoomBlock.objects.filter(end_date__gt=today).exclude(conflict="").count(),
        "failed_sms": SmsMessage.objects.filter(status=SmsMessage.Status.FAILED, created_at__date=day).count(),
        "site_url": settings.SITE_URL,
    }


def recipients():
    from accounts.models import User
    from core.models import HotelSettings

    emails = {e.strip() for e in HotelSettings.load().report_emails.split(",") if e.strip()}
    for user in User.objects.filter(is_active=True).exclude(email=""):
        if user.is_admin or user.role == User.Role.MANAGER:
            emails.add(user.email)
    return sorted(emails)


def send_daily_report(day=None):
    from email.utils import formataddr, parseaddr

    to = recipients()
    if not to:
        return 0
    context = build_report(day)
    hotel = context["hotel"]
    subject = f"{hotel.name} daily report – {context['day']:%a %d %b %Y}"
    text = render_to_string("emails/daily_report.txt", context)
    html = render_to_string("emails/daily_report.html", context)
    _name, address = parseaddr(settings.DEFAULT_FROM_EMAIL)
    message = EmailMultiAlternatives(subject, text, formataddr((hotel.name, address)) if address else None, to)
    message.attach_alternative(html, "text/html")
    try:
        message.send()
    except Exception:  # noqa: BLE001
        logger.exception("Daily report email failed")
        return 0
    return len(to)
