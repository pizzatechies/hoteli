"""SMS sending with a pluggable backend.

SMS_BACKEND=console        – messages are stored and logged, nothing is sent (default)
SMS_BACKEND=africastalking – Africa's Talking (SMS_USERNAME, SMS_API_KEY, optional SMS_SENDER_ID)
                              Use SMS_USERNAME=sandbox with a sandbox API key for testing.
"""

import logging
import re

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import SmsMessage

logger = logging.getLogger("bookings")
MAX_ATTEMPTS = 3


def to_msisdn(phone):
    """+2547XXXXXXXX for Kenyan numbers, or the international number as typed (+…). None if unusable."""
    from mpesa.utils import normalize_phone

    try:
        return "+" + normalize_phone(phone)
    except ValueError:
        digits = re.sub(r"[^\d+]", "", str(phone or ""))
        if digits.startswith("+") and 9 <= len(digits) <= 16:
            return digits
        return None


class SmsError(Exception):
    pass


def _africastalking(message):
    username = settings.SMS_USERNAME
    host = "api.sandbox.africastalking.com" if username == "sandbox" else "api.africastalking.com"
    data = {"username": username, "to": message.to, "message": message.body}
    if settings.SMS_SENDER_ID and username != "sandbox":
        data["from"] = settings.SMS_SENDER_ID
    try:
        resp = requests.post(
            f"https://{host}/version1/messaging", data=data, timeout=15,
            headers={"apiKey": settings.SMS_API_KEY, "Accept": "application/json"},
        )
    except requests.RequestException as exc:
        raise SmsError(f"Could not reach Africa's Talking ({exc.__class__.__name__})") from exc
    if resp.status_code >= 400:
        raise SmsError(f"Africa's Talking error {resp.status_code}: {resp.text[:150]}")
    try:
        recipients = resp.json()["SMSMessageData"]["Recipients"]
    except (ValueError, KeyError, TypeError) as exc:
        raise SmsError(f"Unexpected Africa's Talking response: {resp.text[:150]}") from exc
    if not recipients:
        raise SmsError(resp.json()["SMSMessageData"].get("Message", "Not sent")[:200])
    first = recipients[0]
    if str(first.get("status")).lower() not in ("success", "sent", "submitted", "buffered"):
        raise SmsError(f"{first.get('status')} (code {first.get('statusCode')})")
    return first.get("messageId", ""), first.get("cost", "")


def deliver(message):
    """Try to send one queued message. Safe to call repeatedly."""
    if message.status in (SmsMessage.Status.SENT, SmsMessage.Status.LOGGED):
        return message
    message.attempts += 1
    backend = settings.SMS_BACKEND
    try:
        if backend == "africastalking":
            if not settings.SMS_API_KEY:
                raise SmsError("SMS_API_KEY is not set")
            message.provider_id, message.cost = _africastalking(message)
            message.status = SmsMessage.Status.SENT
        else:
            logger.info("SMS (test mode) to %s: %s", message.to, message.body)
            message.status = SmsMessage.Status.LOGGED
        message.sent_at = timezone.now()
        message.error = ""
    except SmsError as exc:
        message.error = str(exc)[:255]
        message.status = SmsMessage.Status.FAILED if message.attempts >= MAX_ATTEMPTS else SmsMessage.Status.QUEUED
        logger.warning("SMS to %s failed (attempt %s): %s", message.to, message.attempts, exc)
    message.save()
    return message


def queue_sms(phone, body, *, kind=SmsMessage.Kind.CUSTOM, booking=None, user=None, send_now=True):
    """Store an SMS and send it after the current transaction commits. Returns the message or None."""
    to = to_msisdn(phone)
    if not to or not body.strip():
        return None
    message = SmsMessage.objects.create(to=to, body=body.strip()[:640], kind=kind, booking=booking,
                                        sent_by=user if getattr(user, "is_authenticated", False) else None)
    if send_now:
        transaction.on_commit(lambda: deliver(SmsMessage.objects.get(pk=message.pk)))
    return message


def retry_queued():
    """Background job: resend messages that failed temporarily."""
    for message in SmsMessage.objects.filter(status=SmsMessage.Status.QUEUED, attempts__lt=MAX_ATTEMPTS)[:50]:
        deliver(message)


# ------------------------------------------------------------------------------ guest messages
def _enabled(flag):
    from core.models import HotelSettings

    return getattr(HotelSettings.load(), flag, False)


def booking_confirmed(booking):
    if not _enabled("sms_booking_confirmation"):
        return None
    from core.models import HotelSettings

    hotel = HotelSettings.load()
    link = f"{settings.SITE_URL}/booking/{booking.public_token}/"
    body = (f"{hotel.name}: booking {booking.reference} confirmed. {booking.room.room_type.name}, "
            f"{booking.check_in_date:%d %b} - {booking.check_out_date:%d %b} ({booking.nights} "
            f"night{'s' if booking.nights != 1 else ''}). Check-in from {hotel.check_in_time:%H:%M}. "
            f"View or pay: {link}")
    return queue_sms(booking.guest.phone, body, kind=SmsMessage.Kind.BOOKING_CONFIRMED, booking=booking)


def payment_received(payment):
    if not _enabled("sms_payment_receipt") or not payment.booking_id or payment.kind != "PAYMENT":
        return None
    from core.models import HotelSettings

    hotel = HotelSettings.load()
    booking = payment.booking
    balance = max(booking.projected_balance(), 0)
    ref = f" {payment.reference}" if payment.reference else ""
    body = (f"{hotel.name}: received KES {payment.amount:,.0f} for booking {booking.reference} "
            f"({payment.get_method_display()}{ref}). Balance: KES {balance:,.0f}. Asante!")
    return queue_sms(booking.guest.phone, body, kind=SmsMessage.Kind.PAYMENT_RECEIVED, booking=booking)


def checked_in(booking):
    if not _enabled("sms_checkin_welcome"):
        return None
    from core.models import HotelSettings

    hotel = HotelSettings.load()
    body = (f"Karibu {booking.guest.first_name}! You're in room {booking.room.number} at {hotel.name}. "
            f"Check-out {booking.check_out_date:%a %d %b} by {hotel.check_out_time:%H:%M}. "
            f"Need anything? Call {hotel.phone}.")
    return queue_sms(booking.guest.phone, body, kind=SmsMessage.Kind.CHECK_IN, booking=booking)
