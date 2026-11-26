import datetime
from collections import defaultdict
from decimal import ROUND_CEILING, Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from accounts import permissions as P
from accounts.permissions import role_required
from core.models import HotelSettings, log_action
from rooms.models import Room

from . import services
from .forms import (
    BookingForm, CancelForm, ChargeForm, GuestForm, MpesaPromptForm, PaymentForm, RefundForm, VoidForm,
)
from .models import Booking, Charge, Guest, Payment
from .services import BookingError


def _refunds_enabled():
    from mpesa.services import refunds_enabled

    return refunds_enabled()


def _refundable(booking):
    from mpesa.services import refundable_amount

    return refundable_amount(booking)


def _ceil(amount):
    return Decimal(amount).quantize(Decimal("1"), rounding=ROUND_CEILING)


# ------------------------------------------------------------------------------ front desk
@role_required(*P.BOOKING_VIEW)
def front_desk(request):
    today = timezone.localdate()
    services.expire_pending_holds()
    arrivals = (
        Booking.objects.with_totals()
        .filter(status__in=(Booking.Status.PENDING, Booking.Status.CONFIRMED), check_in_date__lte=today)
        .select_related("guest", "room", "room__room_type").order_by("check_in_date", "room__number")
    )
    departures = (
        Booking.objects.with_totals().filter(status=Booking.Status.CHECKED_IN, check_out_date__lte=today)
        .select_related("guest", "room").order_by("check_out_date", "room__number")
    )
    in_house = (
        Booking.objects.with_totals().filter(status=Booking.Status.CHECKED_IN)
        .select_related("guest", "room", "room__room_type").order_by("room__number")
    )
    upcoming = (
        Booking.objects.filter(
            status__in=(Booking.Status.PENDING, Booking.Status.CONFIRMED),
            check_in_date__gt=today, check_in_date__lte=today + datetime.timedelta(days=7),
        ).select_related("guest", "room").order_by("check_in_date")
    )
    return render(request, "bookings/front_desk.html", {
        "today": today, "arrivals": arrivals, "departures": departures, "in_house": in_house,
        "upcoming": upcoming,
    })


@role_required(*P.BOOKING_VIEW)
def guest_register(request):
    """Printable list of in-house guests (statutory guest register)."""
    in_house = (
        Booking.objects.filter(status=Booking.Status.CHECKED_IN)
        .select_related("guest", "room").order_by("room__number")
    )
    return render(request, "bookings/guest_register.html", {"bookings": in_house, "now": timezone.now()})


# ------------------------------------------------------------------------------ bookings
@role_required(*P.BOOKING_VIEW)
def booking_list(request):
    qs = Booking.objects.with_totals().select_related("guest", "room", "room__room_type")
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    source = request.GET.get("source", "")
    date_from = parse_date(request.GET.get("from", "") or "")
    date_to = parse_date(request.GET.get("to", "") or "")
    if q:
        qs = qs.filter(
            Q(reference__icontains=q) | Q(guest__first_name__icontains=q) | Q(guest__last_name__icontains=q)
            | Q(guest__phone__icontains=q) | Q(room__number__iexact=q) | Q(guest__id_number__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    if source:
        qs = qs.filter(source=source)
    if date_from:
        qs = qs.filter(check_out_date__gt=date_from)
    if date_to:
        qs = qs.filter(check_in_date__lte=date_to)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "bookings/booking_list.html", {
        "page": page, "q": q, "status": status, "source": source,
        "date_from": request.GET.get("from", ""), "date_to": request.GET.get("to", ""),
        "statuses": Booking.Status.choices, "sources": Booking.Source.choices,
    })


@role_required(*P.FRONT_DESK)
def booking_create(request):
    today = timezone.localdate()
    initial = {
        "check_in_date": parse_date(request.GET.get("check_in", "") or "") or today,
        "check_out_date": parse_date(request.GET.get("check_out", "") or "") or today + datetime.timedelta(days=1),
    }
    if request.GET.get("room"):
        initial["room"] = request.GET["room"]
    selected_guest = None
    if request.GET.get("guest"):
        selected_guest = Guest.objects.filter(pk=request.GET["guest"]).first()
        if selected_guest:
            initial["guest"] = selected_guest.pk
    form = BookingForm(request.POST or None, initial=initial)
    if request.method == "POST":
        if form.data.get("guest"):
            selected_guest = Guest.objects.filter(pk=form.data.get("guest")).first()
        if form.is_valid():
            d = form.cleaned_data
            from rooms.pricing import quote

            price = quote(d["room"].room_type, d["check_in_date"], d["check_out_date"],
                          promo_code=d.get("promo_code", ""), corporate=d.get("corporate_account"))
            if d.get("promo_code") and price.promo_error and d["rate"] is None:
                form.add_error("promo_code", price.promo_error)
                return render(request, "bookings/booking_form.html", {"form": form, "selected_guest": selected_guest})
            try:
                with transaction.atomic():
                    guest = d["guest"] or Guest.objects.create(
                        first_name=d["first_name"].strip(), last_name=d["last_name"].strip(),
                        phone=d["phone"].strip(), email=d["email"], id_type=d["id_type"] or Guest.IDType.NATIONAL_ID,
                        id_number=d["id_number"].strip(), nationality=d["nationality"] or "Kenyan",
                    )
                    booking = services.create_booking(
                        guest=guest, room=d["room"], check_in=d["check_in_date"], check_out=d["check_out_date"],
                        adults=d["adults"], children=d["children"], rate=d["rate"], source=d["source"],
                        status=d["status"], special_requests=d["special_requests"],
                        internal_notes=d["internal_notes"], user=request.user, price=price,
                    )
            except BookingError as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, f"Booking {booking.reference} created for {booking.guest}.")
                return redirect("bookings:detail", pk=booking.pk)
    return render(request, "bookings/booking_form.html", {"form": form, "selected_guest": selected_guest})


@role_required(*P.FRONT_DESK)
def booking_edit(request, pk):
    booking = get_object_or_404(Booking.objects.select_related("guest", "room"), pk=pk)
    if not booking.can_edit:
        messages.error(request, "This booking can no longer be changed.")
        return redirect("bookings:detail", pk=pk)
    initial = {
        "check_in_date": booking.check_in_date, "check_out_date": booking.check_out_date,
        "adults": booking.adults, "children": booking.children, "room": booking.room_id, "rate": booking.rate,
        "source": booking.source, "special_requests": booking.special_requests,
        "internal_notes": booking.internal_notes,
    }
    form = BookingForm(request.POST or None, initial=initial, editing=booking)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        check_in = booking.check_in_date if booking.status == Booking.Status.CHECKED_IN else d["check_in_date"]
        rate = d["rate"]
        if rate is None:
            rate = services.default_rate(d["room"].room_type, check_in, d["check_out_date"])
        try:
            services.update_booking(
                booking, room=d["room"], check_in=check_in, check_out=d["check_out_date"], adults=d["adults"],
                children=d["children"], rate=rate, user=request.user, source=d["source"],
                special_requests=d["special_requests"], internal_notes=d["internal_notes"],
            )
        except BookingError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Booking updated.")
            return redirect("bookings:detail", pk=pk)
    return render(request, "bookings/booking_form.html", {"form": form, "booking": booking})


@role_required(*P.BOOKING_VIEW)
def booking_detail(request, pk):
    booking = get_object_or_404(Booking.objects.select_related("guest", "room", "room__room_type", "created_by"),
                                pk=pk)
    if booking.is_expired_hold:
        services.expire_pending_holds()
        booking.refresh_from_db()
    charges = booking.charges.select_related("posted_by", "voided_by")
    payments = booking.payments.select_related("received_by")
    projected_total = booking.projected_total()
    payments_total = booking.payments_total
    amount_due = max(projected_total - payments_total, Decimal("0"))
    mpesa_amount = _ceil(amount_due) if amount_due > 0 else None
    user = request.user
    context = {
        "booking": booking,
        "charges": charges,
        "payments": payments,
        "mpesa_transactions": booking.mpesa_transactions.all()[:10],
        "charges_total": booking.charges_total,
        "payments_total": payments_total,
        "balance": booking.balance,
        "projected_total": projected_total,
        "amount_due": amount_due,
        "charge_form": ChargeForm(initial={"service_date": timezone.localdate(), "quantity": 1},
                                  auto_id="charge_%s"),
        "payment_form": PaymentForm(initial={"amount": amount_due if amount_due > 0 else None}, auto_id="pay_%s"),
        "mpesa_form": MpesaPromptForm(initial={"phone": booking.guest.phone, "amount": mpesa_amount},
                                      auto_id="mpesa_%s"),
        "refund_form": RefundForm(initial={"amount": -booking.balance if booking.balance < 0 else None},
                                  auto_id="refund_%s"),
        "cancel_form": CancelForm(auto_id="cancel_%s"),
        "void_form": VoidForm(auto_id="void_%s"),
        "hk_tasks": booking.hk_tasks.all()[:5],
        "pos_orders": booking.pos_orders.all()[:10],
        "active_tx": request.GET.get("tx", ""),
        "mpesa_refunds": booking.mpesa_refunds.all()[:10],
        "mpesa_refunds_enabled": _refunds_enabled(),
        "refundable": _refundable(booking),
        "can_front_desk": user.has_role(*P.FRONT_DESK),
        "can_take_payment": user.has_role(*P.BOOKING_VIEW),
        "can_void": user.has_role(*P.FINANCE),
        "can_override": user.has_role(*P.MANAGEMENT),
        "allow_balance_checkout": HotelSettings.load().allow_checkout_with_balance,
        "room_ready": booking.room.is_ready,
    }
    return render(request, "bookings/booking_detail.html", context)


def _action(request, pk, func, success, **kwargs):
    booking = get_object_or_404(Booking, pk=pk)
    try:
        func(booking, user=request.user, **kwargs)
    except BookingError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, success)
    return redirect("bookings:detail", pk=pk)


@role_required(*P.FRONT_DESK)
@require_POST
def booking_check_in(request, pk):
    return _action(request, pk, services.check_in, "Guest checked in. Hand over the key card!",
                   override_dirty=bool(request.POST.get("override_dirty")))


@role_required(*P.FRONT_DESK)
@require_POST
def booking_check_out(request, pk):
    allow = bool(request.POST.get("allow_balance")) and request.user.has_role(*P.MANAGEMENT)
    return _action(request, pk, services.check_out, "Guest checked out. Room sent to housekeeping.",
                   allow_balance=allow)


@role_required(*P.FRONT_DESK)
@require_POST
def booking_cancel(request, pk):
    form = CancelForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Give a reason for the cancellation.")
        return redirect("bookings:detail", pk=pk)
    return _action(request, pk, services.cancel_booking, "Booking cancelled.",
                   reason=form.cleaned_data["reason"], fee=form.cleaned_data["fee"])


@role_required(*P.FRONT_DESK)
@require_POST
def booking_no_show(request, pk):
    return _action(request, pk, services.mark_no_show, "Booking marked as no-show.")


@role_required(*P.FRONT_DESK)
@require_POST
def booking_confirm(request, pk):
    booking = get_object_or_404(Booking, pk=pk)
    if booking.status != Booking.Status.PENDING:
        messages.error(request, "Only pending bookings can be confirmed.")
    else:
        booking.status = Booking.Status.CONFIRMED
        booking.expires_at = None
        booking.save(update_fields=["status", "expires_at", "updated_at"])
        log_action(request.user, "booking.confirm", booking, f"Manually confirmed {booking.reference}")
        transaction.on_commit(lambda: services.notify_booking_confirmed(booking))
        messages.success(request, "Booking confirmed.")
    return redirect("bookings:detail", pk=pk)


@role_required(*P.FRONT_DESK)
@require_POST
def booking_resend_confirmation(request, pk):
    booking = get_object_or_404(Booking.objects.select_related("guest"), pk=pk)
    if services.send_booking_confirmation(booking):
        messages.success(request, f"Confirmation emailed to {booking.guest.email}.")
    else:
        messages.error(request, "Could not send: the booking must be confirmed and the guest needs an email.")
    return redirect("bookings:detail", pk=pk)


# ------------------------------------------------------------------------------ folio
@role_required(*P.FRONT_DESK)
@require_POST
def charge_add(request, pk):
    booking = get_object_or_404(Booking, pk=pk)
    form = ChargeForm(request.POST)
    if form.is_valid():
        d = form.cleaned_data
        try:
            services.post_charge(booking, category=d["category"], description=d["description"],
                                 unit_price=d["unit_price"], quantity=d["quantity"],
                                 service_date=d["service_date"], user=request.user)
        except BookingError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Charge posted.")
    else:
        messages.error(request, "Charge not posted: " + "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect("bookings:detail", pk=pk)


@role_required(*P.FINANCE)
@require_POST
def charge_void(request, pk, charge_id):
    charge = get_object_or_404(Charge, pk=charge_id, booking_id=pk)
    form = VoidForm(request.POST)
    if not form.is_valid():
        messages.error(request, "A reason is required to void a charge.")
    else:
        try:
            services.void_charge(charge, user=request.user, reason=form.cleaned_data["reason"])
        except BookingError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Charge voided.")
    return redirect("bookings:detail", pk=pk)


@role_required(*P.BOOKING_VIEW)
@require_POST
def payment_add(request, pk):
    from mpesa.services import record_manual_mpesa_payment

    booking = get_object_or_404(Booking, pk=pk)
    form = PaymentForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Payment not recorded: " + "; ".join(e for errs in form.errors.values() for e in errs))
        return redirect("bookings:detail", pk=pk)
    d = form.cleaned_data
    try:
        if d["method"] == Payment.Method.MPESA:
            payment = record_manual_mpesa_payment(booking=booking, code=d["reference"], amount=d["amount"],
                                                  user=request.user, notes=d["notes"])
        else:
            payment = services.record_payment(booking=booking, amount=d["amount"], method=d["method"],
                                              reference=d["reference"], notes=d["notes"], user=request.user)
    except BookingError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Payment {payment.receipt_number} of {payment.amount:,.2f} recorded.")
    return redirect("bookings:detail", pk=pk)


@role_required(*P.FINANCE)
@require_POST
def payment_refund(request, pk):
    booking = get_object_or_404(Booking, pk=pk)
    form = RefundForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Refund not recorded: check the amount and reason.")
        return redirect("bookings:detail", pk=pk)
    d = form.cleaned_data
    try:
        services.record_payment(booking=booking, amount=d["amount"], method=d["method"], reference=d["reference"],
                                notes=d["notes"], user=request.user, kind=Payment.Kind.REFUND)
    except BookingError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Refund recorded.")
    return redirect("bookings:detail", pk=pk)


@role_required(*P.FINANCE)
@require_POST
def payment_void(request, payment_id):
    payment = get_object_or_404(Payment, pk=payment_id)
    form = VoidForm(request.POST)
    if not form.is_valid():
        messages.error(request, "A reason is required to void a payment.")
    else:
        try:
            services.void_payment(payment, user=request.user, reason=form.cleaned_data["reason"])
        except BookingError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Payment {payment.receipt_number} voided.")
    if payment.booking_id:
        return redirect("bookings:detail", pk=payment.booking_id)
    return redirect("pos:order", pk=payment.order_id)


@role_required(*P.BOOKING_VIEW)
def invoice(request, pk):
    booking = get_object_or_404(Booking.objects.select_related("guest", "room", "room__room_type"), pk=pk)
    charges = booking.charges.filter(is_void=False)
    payments = booking.payments.filter(is_void=False)
    hotel = HotelSettings.load()
    total = booking.charges_total
    return render(request, "bookings/invoice.html", {
        "booking": booking, "charges": charges, "payments": payments, "total": total,
        "paid": booking.payments_total, "balance": booking.balance,
        "tax": hotel.tax_breakdown(total) if hotel.show_tax_breakdown else None,
        "printed_at": timezone.now(),
    })


@role_required(*P.CASHIERS)
def receipt(request, payment_id):
    payment = get_object_or_404(Payment.objects.select_related("booking__guest", "order", "received_by"),
                                pk=payment_id)
    return render(request, "bookings/receipt.html", {"payment": payment, "printed_at": timezone.now()})


@role_required(*P.FINANCE)
def payment_list(request):
    qs = Payment.objects.select_related("booking__guest", "order", "received_by")
    method = request.GET.get("method", "")
    q = request.GET.get("q", "").strip()
    date_from = parse_date(request.GET.get("from", "") or "")
    date_to = parse_date(request.GET.get("to", "") or "")
    if method:
        qs = qs.filter(method=method)
    if q:
        qs = qs.filter(Q(receipt_number__icontains=q) | Q(reference__icontains=q)
                       | Q(booking__reference__icontains=q) | Q(booking__guest__last_name__icontains=q))
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(request, "bookings/payment_list.html", {
        "page": page, "methods": Payment.Method.choices, "method": method, "q": q,
        "date_from": request.GET.get("from", ""), "date_to": request.GET.get("to", ""),
    })


# ------------------------------------------------------------------------------ tape chart
@role_required(*P.BOOKING_VIEW)
def tape_chart(request):
    today = timezone.localdate()
    start = parse_date(request.GET.get("start", "") or "") or today - datetime.timedelta(days=1)
    try:
        days = min(max(int(request.GET.get("days", 14)), 7), 31)
    except ValueError:
        days = 14
    end = start + datetime.timedelta(days=days)
    dates = [start + datetime.timedelta(days=i) for i in range(days)]
    rooms = Room.objects.filter(is_active=True).select_related("room_type").order_by(
        "room_type__display_order", "room_type__name", "number")
    bookings = (
        Booking.objects.filter(check_in_date__lt=end, check_out_date__gt=start)
        .exclude(status__in=(Booking.Status.CANCELLED, Booking.Status.NO_SHOW))
        .select_related("guest")
    )
    by_room = defaultdict(list)
    for b in bookings:
        by_room[b.room_id].append(b)
    from types import SimpleNamespace

    from channel_sync.models import RoomBlock

    for block in RoomBlock.objects.filter(start_date__lt=end, end_date__gt=start).select_related("calendar"):
        by_room[block.room_id].append(SimpleNamespace(
            check_in_date=block.start_date, check_out_date=block.end_date, block=block, pk=None))
    rows = []
    for room in rooms:
        stays = sorted(by_room[room.id], key=lambda b: b.check_in_date)
        cells, day = [], start
        while day < end:
            stay = next((b for b in stays if b.check_in_date <= day < b.check_out_date), None)
            if stay:
                span_end = min(stay.check_out_date, end)
                cells.append({"booking": stay, "span": (span_end - day).days,
                              "cut_left": stay.check_in_date < day, "cut_right": stay.check_out_date > end})
                day = span_end
            else:
                cells.append({"date": day, "span": 1, "past": day < today})
                day += datetime.timedelta(days=1)
        rows.append({"room": room, "cells": cells})
    return render(request, "bookings/tape_chart.html", {
        "rows": rows, "dates": dates, "start": start, "days": days, "today": today,
        "prev": start - datetime.timedelta(days=days), "next": end,
    })


# ------------------------------------------------------------------------------ JSON helpers
@role_required(*P.BOOKING_VIEW)
def availability_json(request):
    ci = parse_date(request.GET.get("check_in", "") or "")
    co = parse_date(request.GET.get("check_out", "") or "")
    if not ci or not co or co <= ci:
        return JsonResponse({"rooms": [], "error": "Choose valid dates."})
    exclude = None
    if request.GET.get("exclude"):
        exclude = Booking.objects.filter(pk=request.GET["exclude"]).first()
    services.expire_pending_holds()
    rooms = services.available_rooms(ci, co, exclude_booking=exclude)
    rates = {}
    data = []
    for room in rooms:
        rt = room.room_type
        if rt.pk not in rates:
            rates[rt.pk] = services.default_rate(rt, ci, co)
        data.append({
            "id": room.pk, "number": room.number, "type": rt.name, "rate": str(rates[rt.pk]),
            "max_adults": rt.max_adults, "max_occupancy": rt.max_occupancy,
            "hk_status": room.get_hk_status_display(), "ready": room.is_ready,
        })
    return JsonResponse({"rooms": data, "nights": (co - ci).days})


@role_required(*P.CASHIERS)
def guest_search(request):
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse({"results": []})
    qs = Guest.objects.filter(
        Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(phone__icontains=q)
        | Q(email__icontains=q) | Q(id_number__icontains=q)
    )[:10]
    return JsonResponse({"results": [{
        "id": g.pk, "name": g.full_name, "phone": g.phone, "email": g.email, "id_number": g.id_number,
        "vip": g.is_vip, "blacklisted": g.is_blacklisted,
    } for g in qs]})


# ------------------------------------------------------------------------------ guests
@role_required(*P.BOOKING_VIEW)
def guest_list(request):
    qs = Guest.objects.all()
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(phone__icontains=q)
                       | Q(email__icontains=q) | Q(id_number__icontains=q) | Q(company__icontains=q))
    flag = request.GET.get("flag", "")
    if flag == "vip":
        qs = qs.filter(is_vip=True)
    elif flag == "blacklisted":
        qs = qs.filter(is_blacklisted=True)
    page = Paginator(qs.order_by("-created_at"), 25).get_page(request.GET.get("page"))
    return render(request, "bookings/guest_list.html", {"page": page, "q": q, "flag": flag})


@role_required(*P.FRONT_DESK)
def guest_create(request):
    form = GuestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        guest = form.save()
        log_action(request.user, "guest.create", guest)
        messages.success(request, f"Guest {guest} added.")
        if request.POST.get("then") == "book":
            return redirect(f"/staff/bookings/new/?guest={guest.pk}")
        return redirect("bookings:guest_detail", pk=guest.pk)
    return render(request, "bookings/guest_form.html", {"form": form})


@role_required(*P.FRONT_DESK)
def guest_edit(request, pk):
    guest = get_object_or_404(Guest, pk=pk)
    form = GuestForm(request.POST or None, instance=guest)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_action(request.user, "guest.update", guest)
        messages.success(request, "Guest details saved.")
        nxt = request.POST.get("next")
        if nxt and nxt.startswith("/staff/"):
            return redirect(nxt)
        return redirect("bookings:guest_detail", pk=pk)
    return render(request, "bookings/guest_form.html", {"form": form, "guest": guest,
                                                        "next": request.GET.get("next", "")})


@role_required(*P.BOOKING_VIEW)
def guest_detail(request, pk):
    guest = get_object_or_404(Guest, pk=pk)
    bookings = guest.bookings.with_totals().select_related("room", "room__room_type")
    stays = [b for b in bookings if b.status == Booking.Status.CHECKED_OUT]
    return render(request, "bookings/guest_detail.html", {
        "guest": guest, "bookings": bookings, "stay_count": len(stays),
        "nights": sum(b.nights for b in stays),
        "lifetime_value": sum((b.charges_total for b in stays), Decimal("0")),
    })
