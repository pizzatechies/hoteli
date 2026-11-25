import datetime
from decimal import ROUND_CEILING, Decimal

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts import permissions as P
from accounts.permissions import role_required
from bookings import services as booking_services
from bookings.models import Booking
from bookings.services import BookingError
from core.models import HotelSettings, log_action
from mpesa import services as mpesa_services
from mpesa.models import MpesaTransaction
from mpesa.utils import normalize_phone
from pos.models import MenuCategory
from rooms.models import RoomType

from .forms import (
    ContactForm, FacilityForm, GuestDetailsForm, LookupForm, PayForm, SearchForm, WebsiteContentForm,
)
from .models import ContactMessage, Facility, WebsiteContent


def _default_dates():
    today = timezone.localdate()
    return today, today + datetime.timedelta(days=1)


def _search_form(data=None):
    ci, co = _default_dates()
    return SearchForm(data, today=timezone.localdate(),
                      initial={"check_in": ci, "check_out": co, "adults": 2, "children": 0})


def _ceil(value):
    return Decimal(value).quantize(Decimal("1"), rounding=ROUND_CEILING)


# ------------------------------------------------------------------------------ pages
def home(request):
    return render(request, "website/home.html", {
        "search_form": _search_form(),
        "room_types": RoomType.objects.filter(is_active=True)[:6],
        "facilities": Facility.objects.filter(is_active=True)[:8],
    })


def rooms(request):
    return render(request, "website/rooms.html", {
        "room_types": RoomType.objects.filter(is_active=True),
        "search_form": _search_form(),
    })


def room_detail(request, pk):
    rt = get_object_or_404(RoomType, pk=pk, is_active=True)
    today = timezone.localdate()
    upcoming_seasons = rt.seasonal_rates.filter(end_date__gte=today)[:5]
    return render(request, "website/room_detail.html", {
        "rt": rt, "search_form": _search_form(), "seasons": upcoming_seasons,
        "others": RoomType.objects.filter(is_active=True).exclude(pk=rt.pk)[:3],
    })


def dining(request):
    content = WebsiteContent.load()
    categories = []
    if content.show_dining_menu:
        for cat in MenuCategory.objects.filter(is_active=True).prefetch_related("items"):
            items = [i for i in cat.items.all() if i.is_available]
            if items:
                categories.append({"category": cat, "items": items})
    return render(request, "website/dining.html", {"categories": categories})


def facilities(request):
    return render(request, "website/facilities.html", {"facilities": Facility.objects.filter(is_active=True)})


def contact(request):
    form = ContactForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Thank you! Your message has been sent. We'll get back to you shortly.")
        return redirect("website:contact")
    return render(request, "website/contact.html", {"form": form})


# ------------------------------------------------------------------------------ booking engine
def search(request):
    hotel = HotelSettings.load()
    form = _search_form(request.GET or None)
    results = None
    if form.is_bound and form.is_valid():
        d = form.cleaned_data
        results = booking_services.availability_by_room_type(
            d["check_in"], d["check_out"], d["adults"], d["children"], public=True
        )
    return render(request, "website/search.html", {
        "search_form": form, "results": results, "booking_enabled": hotel.website_booking_enabled,
        "query": request.GET.urlencode(),
    })


def book(request, pk):
    hotel = HotelSettings.load()
    if not hotel.website_booking_enabled:
        messages.info(request, "Online booking is currently unavailable. Please call or WhatsApp us.")
        return redirect("website:contact")
    rt = get_object_or_404(RoomType, pk=pk, is_active=True)
    search_form = _search_form(request.GET or None)
    if not search_form.is_valid():
        messages.error(request, "Please choose your dates first.")
        return redirect(reverse("website:search") + "?" + request.GET.urlencode())
    s = search_form.cleaned_data
    ci, co, adults, children = s["check_in"], s["check_out"], s["adults"], s["children"]
    if adults > rt.max_adults or adults + children > rt.max_occupancy:
        messages.error(request, f"{rt.name} sleeps at most {rt.max_adults} adults / {rt.max_occupancy} guests.")
        return redirect(reverse("website:search") + "?" + request.GET.urlencode())
    nights = (co - ci).days
    total = rt.quote(ci, co)
    deposit = booking_services.deposit_for(total, hotel.deposit_percent) if hotel.website_require_deposit else 0

    form = GuestDetailsForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        g = form.cleaned_data
        booking = None
        error = None
        for _attempt in range(3):  # another guest may grab the same room at the same moment
            room = (booking_services.available_rooms(ci, co, room_type=rt, public=True)
                    .order_by("hk_status", "number").first())
            if room is None:
                error = f"Sorry, {rt.name} has just sold out for those dates. Please pick another room."
                break
            try:
                with transaction.atomic():
                    guest = booking_services.find_or_create_guest(
                        first_name=g["first_name"].strip(), last_name=g["last_name"].strip(),
                        phone=g["phone"], email=g["email"],
                    )
                    if hotel.website_require_deposit:
                        status = Booking.Status.PENDING
                        expires = timezone.now() + datetime.timedelta(minutes=hotel.pending_hold_minutes)
                    else:
                        status, expires = Booking.Status.CONFIRMED, None
                    booking = booking_services.create_booking(
                        guest=guest, room=room, check_in=ci, check_out=co, adults=adults, children=children,
                        source=Booking.Source.WEBSITE, status=status, special_requests=g["special_requests"],
                        deposit_required=deposit, expires_at=expires,
                    )
                break
            except BookingError as exc:
                error = str(exc)
                if "blacklisted" in error:
                    error = "We could not complete this booking online. Please contact the hotel."
                    break
        if booking is not None:
            request.session[f"booking_{booking.public_token}"] = True
            return redirect("website:booking", token=booking.public_token)
        form.add_error(None, error or "We could not complete the booking. Please try again.")
    return render(request, "website/book.html", {
        "rt": rt, "form": form, "check_in": ci, "check_out": co, "adults": adults, "children": children,
        "nights": nights, "total": total, "deposit": deposit, "query": request.GET.urlencode(),
    })


def booking_page(request, token):
    booking = get_object_or_404(Booking.objects.select_related("guest", "room", "room__room_type"),
                                public_token=token)
    if booking.is_expired_hold:
        booking_services.expire_pending_holds()
        booking.refresh_from_db()
    hotel = HotelSettings.load()
    paid = booking.payments_total
    projected_total = booking.projected_total()
    amount_due = max(projected_total - paid, Decimal("0"))
    if booking.status == Booking.Status.PENDING:
        pay_amount = _ceil(booking.deposit_outstanding) or _ceil(amount_due)
    else:
        pay_amount = _ceil(amount_due)
    can_pay = booking.status in (Booking.Status.PENDING, Booking.Status.CONFIRMED,
                                 Booking.Status.CHECKED_IN) and pay_amount > 0
    pending_tx = booking.mpesa_transactions.filter(status=MpesaTransaction.Status.PENDING).first()
    return render(request, "website/booking.html", {
        "booking": booking, "paid": paid, "projected_total": projected_total, "amount_due": amount_due,
        "pay_amount": pay_amount, "can_pay": can_pay,
        "pay_form": PayForm(initial={"phone": booking.guest.phone, "amount": pay_amount or None}),
        "pending_tx": pending_tx,
        "paybill": settings.MPESA_TRANSACTION_TYPE == "CustomerPayBillOnline" and not settings.MPESA_SIMULATE,
        "paybill_number": settings.MPESA_C2B_SHORTCODE,
        "successful_payments": booking.payments.filter(is_void=False, kind="PAYMENT"),
        "hotel": hotel,
    })


@require_POST
def booking_pay(request, token):
    booking = get_object_or_404(Booking, public_token=token)
    wants_json = request.headers.get("Accept", "").startswith("application/json")

    def fail(message):
        if wants_json:
            return JsonResponse({"error": message}, status=400)
        messages.error(request, message)
        return redirect("website:booking", token=token)

    if booking.is_expired_hold:
        booking_services.expire_pending_holds()
        booking.refresh_from_db()
    if booking.status not in (Booking.Status.PENDING, Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN):
        return fail("This booking can no longer be paid online. Please contact the hotel.")
    form = PayForm(request.POST)
    if not form.is_valid():
        return fail("Enter a valid M-Pesa number and amount.")
    due = _ceil(max(booking.projected_balance(), Decimal("0")))
    if booking.status == Booking.Status.PENDING:
        amount = _ceil(booking.deposit_outstanding) or due
    else:
        amount = min(form.cleaned_data["amount"], due)
    if amount < 1:
        return fail("Nothing is due on this booking.")
    try:
        normalize_phone(form.cleaned_data["phone"])
        tx = mpesa_services.initiate_stk_push(
            phone=form.cleaned_data["phone"], amount=amount, booking=booking,
            source=MpesaTransaction.Source.WEBSITE,
        )
    except ValueError as exc:
        return fail(str(exc))
    except mpesa_services.MpesaError as exc:
        return fail(str(exc))
    if booking.status == Booking.Status.PENDING and booking.expires_at:
        # Give the guest time to complete the PIN prompt.
        min_expiry = timezone.now() + datetime.timedelta(seconds=settings.MPESA_STK_TIMEOUT_SECONDS)
        if booking.expires_at < min_expiry:
            Booking.objects.filter(pk=booking.pk).update(expires_at=min_expiry)
    if wants_json:
        return JsonResponse({"id": str(tx.uuid), "status": tx.status, "simulated": tx.is_simulated,
                             "message": tx.result_desc, "amount": str(tx.amount)})
    return redirect(reverse("website:booking", args=[token]) + f"?tx={tx.uuid}")


def lookup(request):
    form = LookupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ref = "".join(ch for ch in form.cleaned_data["reference"].upper() if ch.isalnum())
        contact = form.cleaned_data["contact"].strip().lower()
        booking = Booking.objects.filter(reference=ref).select_related("guest").first()
        matched = False
        if booking:
            guest = booking.guest
            if "@" in contact:
                matched = guest.email.lower() == contact
            else:
                try:
                    matched = normalize_phone(contact) == normalize_phone(guest.phone)
                except ValueError:
                    matched = False
        if matched:
            return redirect("website:booking", token=booking.public_token)
        form.add_error(None, "We couldn't find a booking with those details.")
    return render(request, "website/lookup.html", {"form": form})


# ------------------------------------------------------------------------------ staff: website admin
@role_required(*P.MANAGEMENT)
def manage(request):
    content, _ = WebsiteContent.objects.get_or_create(pk=1)
    form = WebsiteContentForm(request.POST or None, instance=content)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_action(request.user, "website.update", content, "Updated website content")
        messages.success(request, "Website content saved.")
        return redirect("website:manage")
    return render(request, "website/manage.html", {
        "form": form, "facilities": Facility.objects.all(),
        "unread": ContactMessage.objects.filter(is_read=False).count(),
    })


@role_required(*P.MANAGEMENT)
def facility_form(request, pk=None):
    facility = get_object_or_404(Facility, pk=pk) if pk else None
    form = FacilityForm(request.POST or None, instance=facility)
    if request.method == "POST":
        if request.POST.get("delete") and facility:
            facility.delete()
            messages.success(request, "Facility removed.")
            return redirect("website:manage")
        if form.is_valid():
            form.save()
            messages.success(request, "Facility saved.")
            return redirect("website:manage")
    return render(request, "rooms/form.html", {
        "form": form, "title": "Edit facility" if facility else "Add facility", "can_delete": bool(facility),
        "help": "Icons come from Bootstrap Icons (icons.getbootstrap.com), e.g. wifi, cup-hot, p-circle.",
    })


@role_required(*P.FRONT_DESK)
def inbox(request):
    qs = ContactMessage.objects.all()
    if request.GET.get("unread"):
        qs = qs.filter(is_read=False)
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "website/inbox.html", {"page": page, "unread_only": bool(request.GET.get("unread"))})


@role_required(*P.FRONT_DESK)
@require_POST
def inbox_toggle(request, pk):
    msg = get_object_or_404(ContactMessage, pk=pk)
    msg.is_read = not msg.is_read
    msg.save(update_fields=["is_read"])
    return redirect(request.POST.get("next") or "website:inbox")

