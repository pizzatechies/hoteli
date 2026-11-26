"""Booking engine: availability, reservations, check-in/out, folio postings and night audit.

Every state-changing function runs inside a database transaction and locks the rows it
modifies, so two receptionists (or a receptionist and the website) cannot double-book a room
or post the same night twice.
"""

import datetime
import logging
from decimal import ROUND_CEILING, Decimal
from email.utils import formataddr, parseaddr

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.template.loader import render_to_string
from django.utils import timezone

from core.models import HotelSettings, log_action
from rooms.models import Room, RoomType

from .models import ZERO, Booking, Charge, Guest, NightAuditRun, Payment

logger = logging.getLogger("bookings")
MAX_STAY_NIGHTS = 365
EXPIRED_HOLD_REASON = "Online booking hold expired (deposit not paid)"


class BookingError(Exception):
    """A business-rule violation with a message safe to show to staff or guests."""


def daterange(start, end):
    day = start
    while day < end:
        yield day
        day += datetime.timedelta(days=1)


# ------------------------------------------------------------------------------ availability
def available_rooms(check_in, check_out, room_type=None, exclude_booking=None, public=False):
    """Rooms free for the whole stay [check_in, check_out)."""
    busy = Booking.objects.active().overlapping(check_in, check_out)
    if exclude_booking is not None:
        busy = busy.exclude(pk=exclude_booking.pk)
    rooms = Room.objects.filter(is_active=True).exclude(pk__in=busy.values("room_id"))
    today = timezone.localdate()
    if check_in <= today or public:
        rooms = rooms.filter(is_out_of_order=False)
    if public:
        rooms = rooms.filter(room_type__is_active=True)
    if room_type is not None:
        rooms = rooms.filter(room_type=room_type)
    return rooms.select_related("room_type").order_by("room_type__display_order", "floor", "number")


def availability_by_room_type(check_in, check_out, adults=1, children=0, public=True):
    """List of dicts for each room type that can host the party, with free rooms and a quote."""
    expire_pending_holds()
    nights = (check_out - check_in).days
    free = available_rooms(check_in, check_out, public=public)
    counts = {}
    for room in free:
        counts.setdefault(room.room_type_id, []).append(room)
    results = []
    types = RoomType.objects.filter(is_active=True) if public else RoomType.objects.all()
    for rt in types:
        if adults > rt.max_adults or adults + children > rt.max_occupancy:
            continue
        total = rt.quote(check_in, check_out)
        rooms = counts.get(rt.id, [])
        results.append({
            "room_type": rt,
            "available": len(rooms),
            "rooms": rooms,
            "total": total,
            "nightly": (total / nights).quantize(Decimal("0.01")) if nights else rt.base_rate,
            "nights": nights,
        })
    return results


def validate_stay(room, check_in, check_out, adults=1, children=0, exclude_booking=None):
    """Raise BookingError if the room cannot be booked for these dates. Locks the room row."""
    if not check_in or not check_out:
        raise BookingError("Please provide both check-in and check-out dates.")
    if check_out <= check_in:
        raise BookingError("Check-out must be at least one day after check-in.")
    if (check_out - check_in).days > MAX_STAY_NIGHTS:
        raise BookingError(f"Stays longer than {MAX_STAY_NIGHTS} nights are not supported.")
    room = Room.objects.select_for_update().select_related("room_type").get(pk=room.pk)
    if not room.is_active:
        raise BookingError(f"Room {room.number} is not in service.")
    staying_put = (
        exclude_booking is not None
        and exclude_booking.status == Booking.Status.CHECKED_IN
        and exclude_booking.room_id == room.pk
    )
    if room.is_out_of_order and check_in <= timezone.localdate() and not staying_put:
        raise BookingError(
            f"Room {room.number} is out of order ({room.out_of_order_reason or 'maintenance'})."
        )
    rt = room.room_type
    if adults > rt.max_adults:
        raise BookingError(f"{rt.name} rooms take at most {rt.max_adults} adult(s).")
    if adults + children > rt.max_occupancy:
        raise BookingError(f"{rt.name} rooms take at most {rt.max_occupancy} guest(s) in total.")
    clash = Booking.objects.active().overlapping(check_in, check_out).filter(room=room)
    if exclude_booking is not None:
        clash = clash.exclude(pk=exclude_booking.pk)
    clash = clash.select_related("guest").first()
    if clash:
        raise BookingError(
            f"Room {room.number} is already booked by {clash.guest} ({clash.reference}) "
            f"from {clash.check_in_date:%d %b} to {clash.check_out_date:%d %b}."
        )
    return room


def default_rate(room_type, check_in, check_out):
    nights = max((check_out - check_in).days, 1)
    return (room_type.quote(check_in, check_out) / nights).quantize(Decimal("0.01"))


def deposit_for(total, percent):
    """Deposit rounded up to the next shilling (M-Pesa only accepts whole amounts)."""
    return (Decimal(total) * Decimal(percent) / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_CEILING)


# ------------------------------------------------------------------------------ reservations
def create_booking(*, guest, room, check_in, check_out, adults=1, children=0, rate=None,
                   source=Booking.Source.WALK_IN, status=Booking.Status.CONFIRMED,
                   special_requests="", internal_notes="", user=None, deposit_required=ZERO,
                   expires_at=None):
    if guest.is_blacklisted:
        raise BookingError(f"{guest} is blacklisted: {guest.blacklist_reason or 'see guest notes'}.")
    with transaction.atomic():
        room = validate_stay(room, check_in, check_out, adults, children)
        if rate is None:
            rate = default_rate(room.room_type, check_in, check_out)
        booking = Booking.objects.create(
            guest=guest, room=room, check_in_date=check_in, check_out_date=check_out,
            adults=adults, children=children, rate=rate, source=source, status=status,
            special_requests=special_requests, internal_notes=internal_notes, created_by=user,
            deposit_required=deposit_required, expires_at=expires_at,
        )
        log_action(user, "booking.create", booking,
                   f"Booked {booking.reference} for {guest} in room {room.number} "
                   f"{check_in:%d %b}–{check_out:%d %b}")
    if status == Booking.Status.CONFIRMED:
        transaction.on_commit(lambda: notify_booking_confirmed(booking))
    return booking


def update_booking(booking, *, room, check_in, check_out, adults, children, rate, user=None, **extra):
    """Amend dates, room, party size or rate. Handles room moves for in-house guests."""
    with transaction.atomic():
        booking = Booking.objects.select_for_update().select_related("room").get(pk=booking.pk)
        if not booking.can_edit:
            raise BookingError(f"A {booking.get_status_display().lower()} booking cannot be changed.")
        if booking.status == Booking.Status.CHECKED_IN:
            if check_in != booking.check_in_date:
                raise BookingError("The guest is already checked in; the arrival date cannot change.")
            if check_out != booking.check_out_date and check_out <= timezone.localdate():
                raise BookingError("To end the stay today, use Check out instead of shortening the booking.")
            last_posted = (
                booking.charges.filter(category=Charge.Category.ROOM, is_void=False)
                .order_by("-service_date").values_list("service_date", flat=True).first()
            )
            if last_posted and check_out <= last_posted:
                raise BookingError(
                    f"Room charges are already posted up to {last_posted:%d %b}. Void them before shortening the stay."
                )
        validate_stay(room, check_in, check_out, adults, children, exclude_booking=booking)
        old_room = booking.room
        changes = []
        if room.pk != old_room.pk:
            changes.append(f"room {old_room.number} → {room.number}")
        if check_in != booking.check_in_date or check_out != booking.check_out_date:
            changes.append(
                f"dates {booking.check_in_date:%d %b}–{booking.check_out_date:%d %b} → {check_in:%d %b}–{check_out:%d %b}"
            )
        if Decimal(rate) != booking.rate:
            changes.append(f"rate {booking.rate} → {rate}")
        booking.room = room
        booking.check_in_date = check_in
        booking.check_out_date = check_out
        booking.adults = adults
        booking.children = children
        booking.rate = rate
        for field, value in extra.items():
            setattr(booking, field, value)
        booking.save()
        if room.pk != old_room.pk and booking.status == Booking.Status.CHECKED_IN:
            from housekeeping.services import create_checkout_task

            Room.objects.filter(pk=old_room.pk).update(hk_status=Room.HKStatus.DIRTY)
            create_checkout_task(old_room, booking, user, note=f"Guest moved to room {room.number}")
        log_action(user, "booking.update", booking, f"Amended {booking.reference}: " + ("; ".join(changes) or "details"))
    return booking


def check_in(booking, user=None, override_dirty=False):
    settings_obj = HotelSettings.load()
    today = timezone.localdate()
    with transaction.atomic():
        booking = Booking.objects.select_for_update().select_related("guest", "room").get(pk=booking.pk)
        room = Room.objects.select_for_update().get(pk=booking.room_id)
        guest = booking.guest
        if booking.status not in (Booking.Status.PENDING, Booking.Status.CONFIRMED):
            raise BookingError(f"Booking is {booking.get_status_display().lower()}; it cannot be checked in.")
        if booking.check_in_date > today:
            raise BookingError(
                f"Arrival is on {booking.check_in_date:%d %b %Y}. Amend the booking dates to check in early."
            )
        if booking.check_out_date <= today:
            raise BookingError("The booked departure date has passed. Amend the check-out date first.")
        if guest.is_blacklisted:
            raise BookingError(f"{guest} is blacklisted: {guest.blacklist_reason or 'see guest notes'}.")
        if settings_obj.require_guest_id_at_checkin and not guest.id_number:
            raise BookingError("Capture the guest's ID or passport number before check-in.")
        if room.is_out_of_order:
            raise BookingError(f"Room {room.number} is out of order. Move the booking to another room.")
        occupant = Booking.objects.filter(room=room, status=Booking.Status.CHECKED_IN).exclude(pk=booking.pk).first()
        if occupant:
            raise BookingError(
                f"Room {room.number} is still occupied by {occupant.guest} ({occupant.reference}). "
                "Check them out or move this booking."
            )
        if not room.is_ready and not override_dirty:
            raise BookingError(
                f"Room {room.number} is marked {room.get_hk_status_display().lower()}. "
                "Have housekeeping clean it, or tick the override if it has been inspected."
            )
        if booking.check_in_date < today:
            note = f"Late arrival: original arrival {booking.check_in_date:%d %b %Y} moved to {today:%d %b %Y}."
            booking.internal_notes = (booking.internal_notes + "\n" + note).strip()
            booking.check_in_date = today
        booking.status = Booking.Status.CHECKED_IN
        booking.actual_check_in = timezone.now()
        booking.expires_at = None
        booking.save()
        log_action(user, "booking.check_in", booking, f"Checked in {guest} to room {room.number} ({booking.reference})")
        from notifications import sms

        checked_in = booking
        transaction.on_commit(lambda: sms.checked_in(checked_in))
    return booking


def post_room_charges(booking, user=None, up_to=None):
    """Post one room charge per night of the stay that has not been charged yet. Idempotent."""
    posted = set(
        booking.charges.filter(category=Charge.Category.ROOM, is_void=False).values_list("service_date", flat=True)
    )
    count = 0
    for night in booking.stay_dates():
        if up_to is not None and night >= up_to:
            break
        if night in posted:
            continue
        try:
            with transaction.atomic():
                Charge.objects.create(
                    booking=booking, category=Charge.Category.ROOM,
                    description=f"Room {booking.room.number} – night of {night:%a %d %b %Y}",
                    service_date=night, quantity=1, unit_price=booking.rate, posted_by=user,
                )
            count += 1
        except IntegrityError:  # posted concurrently by another process
            continue
    return count


def check_out(booking, user=None, allow_balance=False):
    settings_obj = HotelSettings.load()
    today = timezone.localdate()
    with transaction.atomic():
        booking = Booking.objects.select_for_update().select_related("guest", "room").get(pk=booking.pk)
        if booking.status != Booking.Status.CHECKED_IN:
            raise BookingError("Only checked-in guests can be checked out.")
        new_checkout = max(today, booking.check_in_date + datetime.timedelta(days=1))
        if new_checkout != booking.check_out_date:
            kind = "Early" if new_checkout < booking.check_out_date else "Late"
            booking.internal_notes = (
                booking.internal_notes
                + f"\n{kind} departure: booked until {booking.check_out_date:%d %b %Y}, left {today:%d %b %Y}."
            ).strip()
            booking.check_out_date = new_checkout
            booking.save(update_fields=["check_out_date", "internal_notes", "updated_at"])
        post_room_charges(booking, user)
        balance = booking.balance
        if balance > 0 and not (allow_balance or settings_obj.allow_checkout_with_balance):
            raise BookingError(
                f"Outstanding balance of {settings_obj.currency} {balance:,.2f}. "
                "Collect payment before checking out (a manager can override)."
            )
        booking.status = Booking.Status.CHECKED_OUT
        booking.actual_check_out = timezone.now()
        booking.save()
        Room.objects.filter(pk=booking.room_id).update(hk_status=Room.HKStatus.DIRTY)
        from housekeeping.services import create_checkout_task

        create_checkout_task(booking.room, booking, user)
        msg = f"Checked out {booking.guest} from room {booking.room.number} ({booking.reference})"
        if balance > 0:
            msg += f" with outstanding balance {balance:,.2f}"
        log_action(user, "booking.check_out", booking, msg)
    return booking


def cancel_booking(booking, user=None, reason="", fee=None):
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        if not booking.can_cancel:
            raise BookingError(f"A {booking.get_status_display().lower()} booking cannot be cancelled.")
        if fee:
            Charge.objects.create(
                booking=booking, category=Charge.Category.CANCELLATION, description="Cancellation fee",
                unit_price=Decimal(fee), quantity=1, posted_by=user,
            )
        booking.status = Booking.Status.CANCELLED
        booking.cancelled_at = timezone.now()
        booking.cancellation_reason = reason[:255]
        booking.expires_at = None
        booking.save()
        log_action(user, "booking.cancel", booking, f"Cancelled {booking.reference}: {reason}")
    return booking


def mark_no_show(booking, user=None):
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        if booking.status not in (Booking.Status.PENDING, Booking.Status.CONFIRMED):
            raise BookingError("Only pending or confirmed bookings can be marked as no-show.")
        if booking.check_in_date > timezone.localdate():
            raise BookingError("The arrival date has not come yet.")
        booking.status = Booking.Status.NO_SHOW
        booking.expires_at = None
        booking.save()
        log_action(user, "booking.no_show", booking, f"Marked {booking.reference} as no-show")
    return booking


def expire_pending_holds(now=None):
    """Release unpaid online bookings whose hold time has passed. Returns the number released."""
    now = now or timezone.now()
    grace = datetime.timedelta(seconds=settings.MPESA_STK_TIMEOUT_SECONDS)
    released = 0
    candidates = Booking.objects.filter(
        status=Booking.Status.PENDING, expires_at__isnull=False, expires_at__lte=now
    ).values_list("pk", flat=True)
    for pk in list(candidates):
        with transaction.atomic():
            booking = Booking.objects.select_for_update().get(pk=pk)
            if booking.status != Booking.Status.PENDING or not booking.expires_at or booking.expires_at > now:
                continue
            # Do not release while the guest may still be entering their M-Pesa PIN.
            if booking.mpesa_transactions.filter(status="PENDING", created_at__gte=now - grace).exists():
                continue
            if booking.payments_total > 0:
                booking.expires_at = None  # part-paid: leave for the front desk to follow up
                booking.save(update_fields=["expires_at", "updated_at"])
                continue
            booking.status = Booking.Status.CANCELLED
            booking.cancelled_at = now
            booking.cancellation_reason = EXPIRED_HOLD_REASON
            booking.save()
            log_action(None, "booking.expire", booking, f"Released unpaid online booking {booking.reference}")
            released += 1
    return released


def night_audit(business_date=None, user=None):
    """End-of-day routine: post tonight's room charges, mark no-shows and release expired holds."""
    business_date = business_date or timezone.localdate()
    expired = expire_pending_holds()
    posted = 0
    for booking in Booking.objects.filter(status=Booking.Status.CHECKED_IN).select_related("room"):
        if booking.check_in_date > business_date:
            continue
        if booking.check_out_date <= business_date:
            # Guest is still in-house past the booked departure: extend the stay by a night.
            booking.check_out_date = business_date + datetime.timedelta(days=1)
            booking.internal_notes = (
                booking.internal_notes + f"\nStay extended by night audit ({business_date:%d %b %Y}): guest still in-house."
            ).strip()
            booking.save(update_fields=["check_out_date", "internal_notes", "updated_at"])
        posted += post_room_charges(booking, user, up_to=business_date + datetime.timedelta(days=1))
    no_shows = 0
    for booking in Booking.objects.filter(
        status__in=(Booking.Status.PENDING, Booking.Status.CONFIRMED), check_in_date__lt=business_date
    ):
        booking.status = Booking.Status.NO_SHOW
        booking.expires_at = None
        booking.save(update_fields=["status", "expires_at", "updated_at"])
        log_action(user, "booking.no_show", booking, f"Night audit marked {booking.reference} as no-show")
        no_shows += 1
    run, created = NightAuditRun.objects.get_or_create(business_date=business_date, defaults={"run_by": user})
    run.room_charges_posted += posted
    run.no_shows += no_shows
    run.expired_holds += expired
    if user is not None:
        run.run_by = user
    run.save()
    log_action(user, "night_audit", run,
               f"Night audit {business_date}: {posted} room charges, {no_shows} no-shows, {expired} holds released")
    return run


# ------------------------------------------------------------------------------ folio
def post_charge(booking, *, category, description, unit_price, quantity=1, service_date=None, user=None):
    if booking.status in (Booking.Status.CANCELLED, Booking.Status.NO_SHOW) and category not in (
        Charge.Category.CANCELLATION, Charge.Category.OTHER, Charge.Category.DISCOUNT
    ):
        raise BookingError("Only cancellation fees or adjustments can be posted to a cancelled booking.")
    if category == Charge.Category.ROOM:
        raise BookingError("Room nights are posted automatically by night audit and check-out.")
    charge = Charge.objects.create(
        booking=booking, category=category, description=description, unit_price=unit_price,
        quantity=quantity, service_date=service_date or timezone.localdate(), posted_by=user,
    )
    log_action(user, "charge.post", charge, f"Posted {charge.description} {charge.amount} to {booking.reference}")
    return charge


def void_charge(charge, user=None, reason=""):
    if charge.is_void:
        raise BookingError("This charge is already void.")
    if charge.pos_order_id:
        raise BookingError("This charge came from a POS order. Void it from the order instead.")
    charge.is_void = True
    charge.void_reason = reason[:200]
    charge.voided_by = user
    charge.voided_at = timezone.now()
    charge.save()
    log_action(user, "charge.void", charge, f"Voided charge {charge.description} ({charge.amount}): {reason}")
    return charge


def record_payment(*, amount, method, booking=None, order=None, reference="", payer_phone="",
                   notes="", user=None, kind=Payment.Kind.PAYMENT, skip_duplicate_check=False):
    amount = Decimal(amount)
    if amount <= 0:
        raise BookingError("Amount must be greater than zero.")
    if (booking is None) == (order is None):
        raise BookingError("A payment must belong to exactly one booking or order.")
    reference = (reference or "").strip().upper() if method == Payment.Method.MPESA else (reference or "").strip()
    if (method == Payment.Method.MPESA and reference and kind == Payment.Kind.PAYMENT
            and not skip_duplicate_check):
        dup = Payment.objects.filter(method=Payment.Method.MPESA, reference__iexact=reference, is_void=False).first()
        if dup:
            raise BookingError(
                f"M-Pesa code {reference} is already recorded ({dup.receipt_number} on {dup.target_label})."
            )
    if kind == Payment.Kind.REFUND and booking is not None and amount > booking.payments_total:
        raise BookingError("Refund cannot exceed the amount paid.")
    with transaction.atomic():
        payment = Payment.objects.create(
            booking=booking, order=order, amount=amount, method=method, reference=reference[:60],
            payer_phone=payer_phone[:20], notes=notes[:255], received_by=user, kind=kind,
        )
        target = booking.reference if booking else order.number
        if booking is not None and kind == Payment.Kind.PAYMENT:
            from notifications import sms

            transaction.on_commit(lambda: sms.payment_received(Payment.objects.select_related("booking").get(pk=payment.pk)))
        log_action(user, f"payment.{kind.lower()}", payment,
                   f"{payment.get_kind_display()} {payment.receipt_number} {payment.get_method_display()} "
                   f"{amount:,.2f} on {target}")
        if booking is not None:
            on_booking_payment(booking)
        if order is not None:
            from pos.services import on_order_payment

            on_order_payment(order)
    return payment


def on_booking_payment(booking):
    """Confirm pending bookings once the deposit is covered; rescue holds that expired mid-payment."""
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    paid = booking.payments_total
    if booking.status == Booking.Status.PENDING and paid >= booking.deposit_required and paid > 0:
        booking.status = Booking.Status.CONFIRMED
        booking.expires_at = None
        booking.save(update_fields=["status", "expires_at", "updated_at"])
        log_action(None, "booking.confirm", booking, f"{booking.reference} confirmed after deposit of {paid:,.2f}")
        transaction.on_commit(lambda: notify_booking_confirmed(booking))
    elif (booking.status == Booking.Status.CANCELLED and booking.cancellation_reason == EXPIRED_HOLD_REASON
          and paid > 0):
        _reinstate_expired_booking(booking, paid)


def _reinstate_expired_booking(booking, paid):
    """Money arrived after the hold lapsed: rebook the same (or a same-type) room if still free."""
    room = booking.room
    free = available_rooms(booking.check_in_date, booking.check_out_date, exclude_booking=booking)
    if not free.filter(pk=room.pk).exists():
        room = free.filter(room_type=booking.room.room_type).first()
    if room is None:
        note = (f"Payment of {paid:,.2f} received after the hold expired and no {booking.room.room_type} "
                "room is free. Contact the guest to rebook or refund.")
        booking.internal_notes = (booking.internal_notes + "\n" + note).strip()
        booking.save(update_fields=["internal_notes", "updated_at"])
        log_action(None, "booking.late_payment", booking, note)
        return
    booking.room = room
    booking.status = Booking.Status.CONFIRMED if paid >= booking.deposit_required else Booking.Status.PENDING
    booking.cancelled_at = None
    booking.cancellation_reason = ""
    booking.expires_at = None
    booking.internal_notes = (booking.internal_notes + "\nReinstated: payment arrived after hold expired.").strip()
    booking.save()
    log_action(None, "booking.reinstate", booking, f"Reinstated {booking.reference} in room {room.number}")
    if booking.status == Booking.Status.CONFIRMED:
        transaction.on_commit(lambda: notify_booking_confirmed(booking))


def void_payment(payment, user=None, reason=""):
    if payment.is_void:
        raise BookingError("This payment is already void.")
    with transaction.atomic():
        payment.is_void = True
        payment.void_reason = reason[:200]
        payment.voided_by = user
        payment.voided_at = timezone.now()
        payment.save()
        # A wrongly matched paybill payment goes back to the unmatched queue for re-allocation.
        c2b = getattr(payment, "c2b_transaction", None)
        if c2b is not None:
            c2b.payment = None
            c2b.booking = None
            c2b.order = None
            c2b.status = c2b.Status.UNMATCHED
            c2b.save()
        if payment.order_id and payment.order.status == "PAID":
            payment.order.status = "OPEN"
            payment.order.closed_at = None
            payment.order.save(update_fields=["status", "closed_at"])
        log_action(user, "payment.void", payment, f"Voided {payment.receipt_number} ({payment.amount:,.2f}): {reason}")
    return payment


# ------------------------------------------------------------------------------ guests & email
def find_or_create_guest(*, first_name, last_name, phone, email="", **extra):
    """Website helper: reuse an existing profile with the same phone and name/email."""
    from mpesa.utils import normalize_phone

    try:
        normalized = normalize_phone(phone)
    except ValueError:
        normalized = None
    candidates = Guest.objects.all()
    match = None
    if normalized:
        local = "0" + normalized[3:]
        for guest in candidates.filter(phone__in=[phone, normalized, local, "+" + normalized]):
            if (email and guest.email.lower() == email.lower()) or guest.first_name.lower() == first_name.lower():
                match = guest
                break
    if match:
        if email and not match.email:
            match.email = email
            match.save(update_fields=["email", "updated_at"])
        return match
    return Guest.objects.create(first_name=first_name, last_name=last_name, phone=phone, email=email, **extra)


def notify_booking_confirmed(booking):
    """Email and SMS the guest that their booking is confirmed."""
    send_booking_confirmation(booking)
    booking.refresh_from_db()
    if booking.status == Booking.Status.CONFIRMED:
        from notifications import sms

        sms.booking_confirmed(booking)


def send_booking_confirmation(booking):
    booking.refresh_from_db()
    if not booking.guest.email or booking.status != Booking.Status.CONFIRMED:
        return False
    hotel = HotelSettings.load()
    context = {"booking": booking, "hotel": hotel, "site_url": settings.SITE_URL}
    _display, address = parseaddr(settings.DEFAULT_FROM_EMAIL)
    try:
        send_mail(
            subject=f"Booking confirmed – {booking.reference} | {hotel.name}",
            message=render_to_string("emails/booking_confirmation.txt", context),
            from_email=formataddr((hotel.name, address)) if address else settings.DEFAULT_FROM_EMAIL,
            recipient_list=[booking.guest.email],
            fail_silently=False,
        )
    except Exception:  # noqa: BLE001 - email failure must never break a booking
        logger.exception("Failed to send confirmation for %s", booking.reference)
        return False
    Booking.objects.filter(pk=booking.pk).update(confirmation_sent=True)
    return True
