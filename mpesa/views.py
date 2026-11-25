import json
import logging

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.crypto import constant_time_compare
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from accounts import permissions as P
from accounts.permissions import role_required
from bookings.models import Booking
from bookings.services import BookingError
from pos.models import Order

from . import services
from .models import C2BTransaction, MpesaCallbackLog, MpesaTransaction

logger = logging.getLogger("mpesa")


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR", ""))[:60]


def _check_token(token):
    if not constant_time_compare(token, settings.MPESA_CALLBACK_TOKEN):
        raise Http404()


def _read_json(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return None


# ------------------------------------------------------------------------------ Safaricom callbacks
@csrf_exempt
@require_POST
def stk_callback(request, token):
    _check_token(token)
    payload = _read_json(request)
    log = MpesaCallbackLog.objects.create(kind=MpesaCallbackLog.Kind.STK, payload=payload,
                                          remote_addr=_client_ip(request))
    if payload is None:
        log.error = "Invalid JSON body"
        log.save(update_fields=["error"])
        return JsonResponse({"ResultCode": 1, "ResultDesc": "Invalid payload"}, status=400)
    try:
        tx = services.process_stk_callback(payload)
        log.processed = tx is not None
        log.note = (f"{tx.account_reference}: {tx.get_status_display()}" if tx else "Unknown CheckoutRequestID")[:255]
    except Exception as exc:  # noqa: BLE001 - always acknowledge Safaricom, keep the error for staff
        logger.exception("Error processing STK callback")
        log.error = repr(exc)
    log.save()
    return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})


@csrf_exempt
@require_POST
def c2b_validation(request, token):
    _check_token(token)
    payload = _read_json(request)
    MpesaCallbackLog.objects.create(kind=MpesaCallbackLog.Kind.C2B_VALIDATION, payload=payload,
                                    remote_addr=_client_ip(request), processed=True)
    # Accept everything; unmatched payments are queued for manual allocation.
    return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})


@csrf_exempt
@require_POST
def c2b_confirmation(request, token):
    _check_token(token)
    payload = _read_json(request)
    log = MpesaCallbackLog.objects.create(kind=MpesaCallbackLog.Kind.C2B_CONFIRMATION, payload=payload,
                                          remote_addr=_client_ip(request))
    if payload is None:
        log.error = "Invalid JSON body"
        log.save(update_fields=["error"])
        return JsonResponse({"ResultCode": 1, "ResultDesc": "Invalid payload"}, status=400)
    try:
        c2b = services.process_c2b_confirmation(payload)
        log.processed = True
        log.note = f"{c2b.trans_id} {c2b.get_status_display()}"[:255]
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error processing C2B confirmation")
        log.error = repr(exc)
    log.save()
    return JsonResponse({"ResultCode": 0, "ResultDesc": "Success"})


# ------------------------------------------------------------------------------ status polling (public)
def _tx_json(tx):
    return {
        "id": str(tx.uuid),
        "status": tx.status,
        "status_label": tx.get_status_display(),
        "final": tx.status != MpesaTransaction.Status.PENDING,
        "success": tx.status == MpesaTransaction.Status.SUCCESS,
        "message": tx.result_desc,
        "receipt": tx.mpesa_receipt,
        "amount": str(tx.amount),
        "phone": tx.masked_phone,
        "simulated": tx.is_simulated,
    }


@require_GET
def transaction_status(request, uuid):
    tx = get_object_or_404(MpesaTransaction, uuid=uuid)
    tx = services.refresh_transaction_status(tx)
    return JsonResponse(_tx_json(tx))


@require_POST
def simulate(request, uuid):
    if not settings.MPESA_SIMULATE:
        raise Http404()
    tx = get_object_or_404(MpesaTransaction, uuid=uuid)
    if tx.status != MpesaTransaction.Status.PENDING:
        return JsonResponse(_tx_json(tx))
    outcome = request.POST.get("outcome", "success")
    try:
        tx = services.simulate_result(tx, outcome)
    except services.MpesaError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(_tx_json(tx))


# ------------------------------------------------------------------------------ staff
@role_required(*P.CASHIERS)
@require_POST
def stk_start(request):
    """Send an STK push for a booking folio or a POS order (staff initiated)."""
    booking = order = None
    if request.POST.get("booking"):
        if not request.user.has_role(*P.BOOKING_VIEW):
            raise Http404()
        booking = get_object_or_404(Booking, pk=request.POST["booking"])
        back = redirect("bookings:detail", pk=booking.pk)
    elif request.POST.get("order"):
        order = get_object_or_404(Order, pk=request.POST["order"])
        back = redirect("pos:order", pk=order.pk)
    else:
        raise Http404()
    wants_json = request.headers.get("Accept", "").startswith("application/json")
    try:
        tx = services.initiate_stk_push(phone=request.POST.get("phone", ""), amount=request.POST.get("amount") or 0,
                                        booking=booking, order=order, user=request.user)
    except services.MpesaError as exc:
        if wants_json:
            return JsonResponse({"error": str(exc)}, status=400)
        messages.error(request, str(exc))
        return back
    if wants_json:
        return JsonResponse(_tx_json(tx))
    messages.info(request, f"M-Pesa prompt sent to {tx.masked_phone} for KES {tx.amount:,.0f}.")
    back["Location"] += f"?tx={tx.uuid}"
    return back


@role_required(*P.FINANCE, *P.FRONT_DESK)
def transaction_list(request):
    qs = MpesaTransaction.objects.select_related("booking__guest", "order", "initiated_by", "payment")
    status = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()
    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(Q(phone__icontains=q) | Q(mpesa_receipt__icontains=q) | Q(account_reference__icontains=q))
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(request, "mpesa/transaction_list.html", {
        "page": page, "statuses": MpesaTransaction.Status.choices, "status": status, "q": q,
        "unmatched": C2BTransaction.objects.filter(status=C2BTransaction.Status.UNMATCHED).count(),
    })


@role_required(*P.FINANCE, *P.FRONT_DESK)
def transaction_detail(request, pk):
    tx = get_object_or_404(MpesaTransaction.objects.select_related("booking", "order", "payment"), pk=pk)
    if request.method == "POST":
        before = tx.status
        tx = services.refresh_transaction_status(tx, force=True)
        if tx.status == before:
            messages.info(request, f"Still {tx.get_status_display().lower()}. {tx.result_desc}")
        else:
            messages.success(request, f"Status updated: {tx.get_status_display()}.")
        return redirect("mpesa:detail", pk=pk)
    return render(request, "mpesa/transaction_detail.html", {
        "tx": tx,
        "raw_response": json.dumps(tx.raw_response, indent=2) if tx.raw_response else "",
        "raw_callback": json.dumps(tx.raw_callback, indent=2) if tx.raw_callback else "",
    })


@role_required(*P.FINANCE, *P.FRONT_DESK)
def c2b_list(request):
    qs = C2BTransaction.objects.select_related("booking", "order", "payment", "allocated_by")
    status = request.GET.get("status", "")
    if status:
        qs = qs.filter(status=status)
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(request, "mpesa/c2b_list.html", {
        "page": page, "statuses": C2BTransaction.Status.choices, "status": status,
    })


@role_required(*P.FINANCE, *P.FRONT_DESK)
@require_POST
def c2b_allocate(request, pk):
    c2b = get_object_or_404(C2BTransaction, pk=pk)
    ref = request.POST.get("reference", "")
    if request.POST.get("ignore"):
        if c2b.payment_id:
            messages.error(request, "Allocated payments cannot be ignored. Void the payment first.")
        else:
            c2b.status = C2BTransaction.Status.IGNORED
            c2b.save(update_fields=["status"])
            messages.success(request, f"{c2b.trans_id} marked as ignored.")
        return redirect("mpesa:c2b_list")
    booking, order = services.match_reference(ref)
    if not booking and not order:
        messages.error(request, f"No booking or order found for '{ref}'.")
        return redirect("mpesa:c2b_list")
    try:
        services.allocate_c2b(c2b, booking=booking, order=order, user=request.user)
    except BookingError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"{c2b.trans_id} allocated to {(booking or order)}.")
    return redirect("mpesa:c2b_list")


@role_required(*P.FINANCE)
def callback_logs(request):
    qs = MpesaCallbackLog.objects.all()
    kind = request.GET.get("kind", "")
    if kind:
        qs = qs.filter(kind=kind)
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    for log in page:
        log.pretty = json.dumps(log.payload, indent=2) if log.payload else ""
    return render(request, "mpesa/callback_logs.html", {
        "page": page, "kinds": MpesaCallbackLog.Kind.choices, "kind": kind,
    })
