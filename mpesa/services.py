"""M-Pesa business logic: start STK pushes, process callbacks, reconcile into folios.

Design notes (the "kinks"):
* Safaricom does not sign callbacks, so callback URLs carry a secret token and every
  callback is matched against a CheckoutRequestID we issued.
* Callbacks can be duplicated, arrive late, or never arrive (e.g. callback URL not reachable
  from the internet). Status polling falls back to Daraja's STK query API, and a late success
  callback is always honoured - even after we marked the request as timed out.
* Payments are created exactly once per transaction (row locks + OneToOne link) and an
  M-Pesa receipt number is never recorded twice.
* Amounts are rounded up to whole shillings (M-Pesa does not accept cents).
"""

import datetime
import logging
import secrets
import string
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from bookings.models import Booking, Payment
from bookings.services import BookingError, record_payment
from core.models import log_action

from .daraja import STILL_PROCESSING_CODE, DarajaClient, DarajaError
from .models import C2BTransaction, MpesaTransaction
from .utils import normalize_phone, parse_mpesa_timestamp, stk_amount

logger = logging.getLogger("mpesa")
S = MpesaTransaction.Status

RESULT_STATUS = {
    "0": S.SUCCESS,
    "1032": S.CANCELLED,
    "1037": S.TIMEOUT,
    "1019": S.TIMEOUT,
}
FRIENDLY_RESULTS = {
    "0": "Payment received.",
    "1": "The customer's M-Pesa balance is insufficient.",
    "17": "M-Pesa declined the request (limit or risk rule). Try a smaller amount or later.",
    "26": "M-Pesa is busy. Please try again shortly.",
    "1001": "The customer has another M-Pesa transaction in progress. Wait a minute and retry.",
    "1019": "The payment request expired before it was completed.",
    "1025": "M-Pesa could not send the prompt. Please try again.",
    "1032": "The customer cancelled the payment on their phone.",
    "1037": "The phone could not be reached (switched off, no network or SIM Toolkit busy).",
    "2001": "Wrong M-Pesa PIN entered.",
    "9999": "M-Pesa could not send the prompt. Please try again.",
}
RESEND_COOLDOWN_SECONDS = 30
MAX_PUSHES_PER_PHONE_10_MIN = 6


class MpesaError(Exception):
    """User-facing M-Pesa problem (bad phone, Daraja rejected the request, throttled, …)."""


def is_simulation():
    return bool(settings.MPESA_SIMULATE)


def mode_label():
    if is_simulation():
        return "Simulation"
    return "Live" if settings.MPESA_ENVIRONMENT == "production" else "Sandbox"


def stk_callback_url():
    path = reverse("mpesa:stk_callback", args=[settings.MPESA_CALLBACK_TOKEN])
    return f"{settings.MPESA_CALLBACK_BASE_URL}{path}"


def c2b_urls():
    token = settings.MPESA_CALLBACK_TOKEN
    base = settings.MPESA_CALLBACK_BASE_URL
    return {
        "confirmation": base + reverse("mpesa:c2b_confirmation", args=[token]),
        "validation": base + reverse("mpesa:c2b_validation", args=[token]),
    }


# ------------------------------------------------------------------------------ STK push
def initiate_stk_push(*, phone, amount, booking=None, order=None, user=None,
                      source=MpesaTransaction.Source.STAFF):
    if (booking is None) == (order is None):
        raise MpesaError("Choose what this payment is for.")
    try:
        msisdn = normalize_phone(phone)
        amount = stk_amount(amount)
    except ValueError as exc:
        raise MpesaError(str(exc)) from exc

    now = timezone.now()
    in_flight = MpesaTransaction.objects.filter(
        status=S.PENDING, booking=booking, order=order,
        created_at__gte=now - datetime.timedelta(seconds=RESEND_COOLDOWN_SECONDS),
    )
    if in_flight.exists():
        raise MpesaError(
            "A payment prompt was sent less than 30 seconds ago. Ask the customer to check their phone, "
            "or wait a moment before resending."
        )
    recent_for_phone = MpesaTransaction.objects.filter(
        phone=msisdn, created_at__gte=now - datetime.timedelta(minutes=10)
    ).count()
    if recent_for_phone >= MAX_PUSHES_PER_PHONE_10_MIN:
        raise MpesaError("Too many payment requests to this number. Please wait a few minutes.")

    if booking is not None:
        account_reference, description = booking.reference, "Room booking"
    else:
        account_reference, description = order.number.replace("-", ""), "Food & drinks"

    tx = MpesaTransaction.objects.create(
        booking=booking, order=order, phone=msisdn, amount=amount,
        account_reference=account_reference[:12], description=description[:13],
        initiated_by=user if getattr(user, "is_authenticated", False) else None,
        source=source, is_simulated=is_simulation(),
    )

    if tx.is_simulated:
        tx.merchant_request_id = f"SIM-{tx.uuid.hex[:12]}"
        tx.checkout_request_id = f"ws_CO_SIM_{tx.uuid.hex}"
        tx.result_desc = "Simulation mode: no real prompt was sent. Use the simulate buttons."
        tx.raw_response = {"ResponseCode": "0", "CustomerMessage": "Simulated request accepted"}
        tx.save()
        return tx

    try:
        data = DarajaClient().stk_push(
            phone=msisdn, amount=amount, account_reference=tx.account_reference,
            description=tx.description, callback_url=stk_callback_url(),
        )
    except DarajaError as exc:
        tx.status = S.FAILED
        tx.result_code = str(exc.code or "")[:20]
        tx.result_desc = str(exc)[:255]
        tx.raw_response = exc.response
        tx.save()
        logger.warning("STK push failed for %s: %s", tx.account_reference, exc)
        raise MpesaError(f"M-Pesa request failed: {exc}") from exc

    tx.merchant_request_id = data.get("MerchantRequestID", "")
    tx.checkout_request_id = data.get("CheckoutRequestID")
    tx.result_desc = (data.get("CustomerMessage") or data.get("ResponseDescription") or "")[:255]
    tx.raw_response = data
    tx.save()
    return tx


def _metadata(callback):
    items = (callback.get("CallbackMetadata") or {}).get("Item") or []
    return {item.get("Name"): item.get("Value") for item in items if isinstance(item, dict)}


def _apply_payment(tx):
    """Create the folio/order payment for a successful transaction (once)."""
    if tx.payment_id:
        return tx.payment
    if tx.mpesa_receipt:
        existing = Payment.objects.filter(
            method=Payment.Method.MPESA, reference__iexact=tx.mpesa_receipt, is_void=False
        ).first()
        if existing:
            tx.payment = existing
            tx.save(update_fields=["payment", "updated_at"])
            return existing
    reference = tx.mpesa_receipt or f"STK-{(tx.checkout_request_id or tx.uuid.hex)[-10:]}"
    note = "M-Pesa STK push" + (" (SIMULATED)" if tx.is_simulated else "")
    if not tx.mpesa_receipt:
        note += " – confirmed by status query, receipt number pending"
    payment = record_payment(
        booking=tx.booking, order=tx.order, amount=tx.amount, method=Payment.Method.MPESA,
        reference=reference, payer_phone=tx.paid_phone or tx.phone, notes=note,
        user=tx.initiated_by, skip_duplicate_check=True,
    )
    tx.payment = payment
    tx.save(update_fields=["payment", "updated_at"])
    return payment


def process_stk_callback(payload):
    """Handle Safaricom's STK result callback. Returns the transaction (or None if unknown)."""
    callback = (payload or {}).get("Body", {}).get("stkCallback")
    if not isinstance(callback, dict):
        raise ValueError("Not an STK callback payload")
    checkout_id = callback.get("CheckoutRequestID")
    result_code = str(callback.get("ResultCode", ""))
    meta = _metadata(callback)

    with transaction.atomic():
        tx = MpesaTransaction.objects.select_for_update().filter(checkout_request_id=checkout_id).first()
        if tx is None:
            logger.warning("STK callback for unknown CheckoutRequestID %s", checkout_id)
            return None
        tx.raw_callback = payload
        receipt = str(meta.get("MpesaReceiptNumber") or "")

        if tx.status == S.SUCCESS:
            # Duplicate callback, or the callback arriving after a status query already confirmed it.
            if receipt and not tx.mpesa_receipt:
                tx.mpesa_receipt = receipt
                tx.transaction_date = parse_mpesa_timestamp(meta.get("TransactionDate"))
                if tx.payment_id and tx.payment.reference.startswith("STK-"):
                    Payment.objects.filter(pk=tx.payment_id).update(
                        reference=receipt, notes="M-Pesa STK push" + (" (SIMULATED)" if tx.is_simulated else "")
                    )
            tx.save()
            return tx

        tx.result_code = result_code
        tx.result_desc = FRIENDLY_RESULTS.get(result_code, callback.get("ResultDesc", ""))[:255]
        if result_code == "0":
            tx.status = S.SUCCESS
            tx.mpesa_receipt = receipt
            if meta.get("Amount") is not None:
                tx.amount = Decimal(str(meta["Amount"])).quantize(Decimal("0.01"))
            tx.transaction_date = parse_mpesa_timestamp(meta.get("TransactionDate"))
            tx.paid_phone = str(meta.get("PhoneNumber") or "")
            tx.save()
            _apply_payment(tx)
        else:
            tx.status = RESULT_STATUS.get(result_code, S.FAILED)
            tx.save()
    return tx


def refresh_transaction_status(tx, force=False):
    """If a push is still pending, ask Daraja for its status (rate limited). Returns the tx."""
    if tx.status != S.PENDING or tx.is_simulated or not tx.checkout_request_id:
        return tx
    now = timezone.now()
    age = (now - tx.created_at).total_seconds()
    if not force:
        if age < settings.MPESA_QUERY_AFTER_SECONDS:
            return tx
        if tx.last_queried_at and (now - tx.last_queried_at).total_seconds() < 10:
            return tx
    try:
        data = DarajaClient().stk_query(tx.checkout_request_id)
    except DarajaError as exc:
        with transaction.atomic():
            tx = MpesaTransaction.objects.select_for_update().get(pk=tx.pk)
            tx.last_queried_at = now
            tx.query_attempts += 1
            if tx.status == S.PENDING and age > settings.MPESA_STK_TIMEOUT_SECONDS:
                tx.status = S.TIMEOUT
                tx.result_desc = (
                    "No final answer from M-Pesa. If the customer was charged, the payment will be "
                    "matched automatically when M-Pesa confirms it."
                )
            elif exc.code != STILL_PROCESSING_CODE:
                logger.warning("STK query failed for %s: %s", tx.checkout_request_id, exc)
            tx.save()
        return tx

    code = str(data.get("ResultCode", ""))
    with transaction.atomic():
        tx = MpesaTransaction.objects.select_for_update().get(pk=tx.pk)
        tx.last_queried_at = now
        tx.query_attempts += 1
        if tx.status == S.PENDING and code:
            tx.result_code = code
            tx.result_desc = FRIENDLY_RESULTS.get(code, data.get("ResultDesc", ""))[:255]
            tx.status = RESULT_STATUS.get(code, S.FAILED)
            tx.save()
            if tx.status == S.SUCCESS:
                _apply_payment(tx)
        else:
            tx.save()
    return tx


def simulate_result(tx, outcome="success"):
    """Simulation mode: feed a realistic callback through the real processing path."""
    if not tx.is_simulated:
        raise MpesaError("Only simulated transactions can be completed this way.")
    codes = {"success": 0, "cancel": 1032, "insufficient": 1, "timeout": 1037, "wrong_pin": 2001}
    code = codes.get(outcome, 0)
    callback = {
        "MerchantRequestID": tx.merchant_request_id,
        "CheckoutRequestID": tx.checkout_request_id,
        "ResultCode": code,
        "ResultDesc": FRIENDLY_RESULTS.get(str(code), "Simulated"),
    }
    if code == 0:
        receipt = "S" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(9))
        callback["CallbackMetadata"] = {"Item": [
            {"Name": "Amount", "Value": float(tx.amount)},
            {"Name": "MpesaReceiptNumber", "Value": receipt},
            {"Name": "TransactionDate", "Value": int(timezone.localtime().strftime("%Y%m%d%H%M%S"))},
            {"Name": "PhoneNumber", "Value": int(tx.phone)},
        ]}
    return process_stk_callback({"Body": {"stkCallback": callback}})


# ------------------------------------------------------------------------------ C2B (Paybill)
def _clean_reference(value):
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def match_reference(bill_ref):
    """Find the booking or POS order an account number refers to."""
    ref = _clean_reference(bill_ref)
    if not ref:
        return None, None
    booking = Booking.objects.filter(reference=ref).first()
    if booking:
        return booking, None
    if ref.startswith("ORD") and ref[3:].isdigit():
        from pos.models import Order

        return None, Order.objects.filter(pk=int(ref[3:])).first()
    return None, None


def process_c2b_confirmation(payload):
    trans_id = str(payload.get("TransID") or "").strip()
    if not trans_id:
        raise ValueError("C2B confirmation without TransID")
    with transaction.atomic():
        c2b, created = C2BTransaction.objects.select_for_update().get_or_create(
            trans_id=trans_id,
            defaults={
                "trans_type": str(payload.get("TransactionType") or "")[:40],
                "trans_time": parse_mpesa_timestamp(payload.get("TransTime")),
                "amount": str(payload.get("TransAmount") or "0"),
                "business_short_code": str(payload.get("BusinessShortCode") or "")[:20],
                "bill_ref_number": str(payload.get("BillRefNumber") or "")[:60],
                "msisdn": str(payload.get("MSISDN") or "")[:80],
                "first_name": str(payload.get("FirstName") or "")[:60],
                "middle_name": str(payload.get("MiddleName") or "")[:60],
                "last_name": str(payload.get("LastName") or "")[:60],
                "org_account_balance": str(payload.get("OrgAccountBalance") or "")[:40],
                "raw": payload,
            },
        )
        if not created:
            return c2b  # Safaricom retries confirmations; process each code once.
        booking, order = match_reference(c2b.bill_ref_number)
        if booking or order:
            try:
                allocate_c2b(c2b, booking=booking, order=order, auto=True)
            except BookingError as exc:
                logger.warning("Could not auto-allocate %s: %s", trans_id, exc)
    return c2b


def allocate_c2b(c2b, *, booking=None, order=None, user=None, auto=False):
    if c2b.payment_id:
        raise BookingError("This M-Pesa payment is already allocated.")
    existing = Payment.objects.filter(
        method=Payment.Method.MPESA, reference__iexact=c2b.trans_id, is_void=False
    ).first()
    if existing:
        payment = existing  # staff already keyed this code in manually
    else:
        payment = record_payment(
            booking=booking, order=order, amount=c2b.amount, method=Payment.Method.MPESA,
            reference=c2b.trans_id, payer_phone=c2b.msisdn[:20],
            notes=f"Paybill payment from {c2b.payer_name or c2b.msisdn}", user=user,
        )
    c2b.payment = payment
    c2b.booking = payment.booking
    c2b.order = payment.order
    c2b.status = C2BTransaction.Status.MATCHED if auto else C2BTransaction.Status.ALLOCATED
    c2b.allocated_by = user
    c2b.allocated_at = timezone.now()
    c2b.save()
    if not auto:
        log_action(user, "mpesa.c2b_allocate", c2b, f"Allocated {c2b.trans_id} to {payment.target_label}")
    return payment


def record_manual_mpesa_payment(*, booking=None, order=None, code, amount, user=None, payer_phone="", notes=""):
    """Staff keyed in an M-Pesa code. If it is sitting in the unmatched paybill queue, use that."""
    code = _clean_reference(code)
    c2b = C2BTransaction.objects.filter(trans_id__iexact=code, payment__isnull=True).first()
    if c2b is not None:
        return allocate_c2b(c2b, booking=booking, order=order, user=user)
    return record_payment(
        booking=booking, order=order, amount=amount, method=Payment.Method.MPESA, reference=code,
        payer_phone=payer_phone, notes=notes or "M-Pesa (entered manually)", user=user,
    )
