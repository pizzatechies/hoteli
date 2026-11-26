import csv
import datetime

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts import permissions as P
from accounts.permissions import role_required
from bookings.models import ZERO, Booking, NightAuditRun, signed_payment_sum
from bookings.services import night_audit
from housekeeping.models import HousekeepingTask, MaintenanceRequest
from mpesa.models import C2BTransaction, MpesaTransaction
from rooms.models import Room

from . import reports
from .branding import read_logo
from .forms import DateRangeForm, HotelIdentityForm, HotelSettingsForm, LogoUploadForm
from .models import AuditLog, BrandAsset, HotelSettings, log_action


def _ota_conflicts(today):
    from channel_sync.models import RoomBlock

    return RoomBlock.objects.filter(end_date__gt=today).exclude(conflict="").count()


def _month_start(day):
    return day.replace(day=1)


def dashboard(request):
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    user = request.user
    if user.role == user.Role.HOUSEKEEPING and not user.is_admin:
        return redirect("housekeeping:board")
    if user.role == user.Role.RESTAURANT and not user.is_admin:
        return redirect("pos:home")

    today = timezone.localdate()
    rooms_total = Room.objects.filter(is_active=True).count()
    in_house = Booking.objects.filter(status=Booking.Status.CHECKED_IN)
    occupied = in_house.count()
    arrivals = (
        Booking.objects.filter(status__in=(Booking.Status.PENDING, Booking.Status.CONFIRMED), check_in_date=today)
        .select_related("guest", "room", "room__room_type")
    )
    departures = (
        Booking.objects.filter(status=Booking.Status.CHECKED_IN, check_out_date__lte=today)
        .select_related("guest", "room")
    )
    collected_today = reports.payments_in_range(today, today).aggregate(t=Sum(signed_payment_sum()))["t"] or ZERO
    collected_month = (
        reports.payments_in_range(_month_start(today), today).aggregate(t=Sum(signed_payment_sum()))["t"] or ZERO
    )
    hk_counts = dict(Room.objects.filter(is_active=True).values_list("hk_status").annotate(c=Count("id")))
    ooo = Room.objects.filter(is_active=True, is_out_of_order=True).count()

    start = today - datetime.timedelta(days=13)
    daily = dict(
        reports.payments_in_range(start, today).annotate(d=TruncDate("created_at"))
        .values("d").annotate(t=Sum(signed_payment_sum())).values_list("d", "t")
    )
    chart_days = [start + datetime.timedelta(days=i) for i in range(14)]
    forecast_counts = reports.occupancy_counts(
        today, today + datetime.timedelta(days=13), statuses=Booking.ACTIVE_STATUSES
    )
    forecast_days = [today + datetime.timedelta(days=i) for i in range(14)]

    context = {
        "today": today,
        "rooms_total": rooms_total,
        "occupied": occupied,
        "occupancy_pct": round(occupied * 100 / rooms_total) if rooms_total else 0,
        "arrivals": arrivals,
        "departures": departures,
        "collected_today": collected_today,
        "collected_month": collected_month,
        "pending_web": Booking.objects.filter(status=Booking.Status.PENDING, source=Booking.Source.WEBSITE).count(),
        "hk": {
            "clean": hk_counts.get(Room.HKStatus.CLEAN, 0) + hk_counts.get(Room.HKStatus.INSPECTED, 0),
            "dirty": hk_counts.get(Room.HKStatus.DIRTY, 0),
            "cleaning": hk_counts.get(Room.HKStatus.CLEANING, 0),
            "ooo": ooo,
        },
        "open_tasks": HousekeepingTask.objects.filter(
            status__in=(HousekeepingTask.Status.PENDING, HousekeepingTask.Status.IN_PROGRESS)
        ).count(),
        "open_maintenance": MaintenanceRequest.objects.filter(status__in=MaintenanceRequest.OPEN_STATUSES).count(),
        "unmatched_c2b": C2BTransaction.objects.filter(status=C2BTransaction.Status.UNMATCHED).count(),
        "ota_conflicts": _ota_conflicts(today),
        "recent_mpesa": MpesaTransaction.objects.select_related("booking", "order")[:8],
        "chart_labels": [d.strftime("%d %b") for d in chart_days],
        "chart_values": [float(daily.get(d) or 0) for d in chart_days],
        "forecast_labels": [d.strftime("%a %d") for d in forecast_days],
        "forecast_values": [
            round(forecast_counts.get(d, 0) * 100 / rooms_total) if rooms_total else 0 for d in forecast_days
        ],
        "last_audit": NightAuditRun.objects.first(),
    }
    return render(request, "core/dashboard.html", context)


@role_required(*P.FRONT_DESK)
@require_POST
def run_night_audit(request):
    run = night_audit(user=request.user)
    messages.success(
        request,
        f"Night audit for {run.business_date:%d %b %Y} complete: room charges posted to date "
        f"{run.room_charges_posted}, no-shows {run.no_shows}, expired holds released {run.expired_holds}.",
    )
    return redirect(request.POST.get("next") or "core:dashboard")


def _report_range(request):
    today = timezone.localdate()
    form = DateRangeForm(request.GET or None, initial={"start": _month_start(today), "end": today})
    if form.is_bound and form.is_valid():
        return form, form.cleaned_data["start"], form.cleaned_data["end"]
    if form.is_bound:
        messages.error(request, "Invalid date range; showing this month.")
    form = DateRangeForm(initial={"start": _month_start(today), "end": today})
    return form, _month_start(today), today


@role_required(*P.REPORTS)
def report_view(request):
    form, start, end = _report_range(request)
    rows, summary = reports.daily_stats(start, end)
    context = {
        "form": form, "start": start, "end": end, "rows": rows, "summary": summary,
        "by_category": reports.revenue_by_category(start, end),
        "by_method": reports.payments_by_method(start, end),
        "outstanding": reports.outstanding_balances(),
        "credits": reports.credit_balances(),
        "mpesa_stk": MpesaTransaction.objects.filter(
            status=MpesaTransaction.Status.SUCCESS, created_at__date__range=(start, end)
        ).aggregate(t=Sum("amount"), c=Count("id")),
        "mpesa_c2b": C2BTransaction.objects.filter(created_at__date__range=(start, end)).aggregate(
            t=Sum("amount"), c=Count("id")
        ),
        "chart_labels": [r["date"].strftime("%d %b") for r in rows],
        "chart_occupancy": [float(r["occupancy"]) for r in rows],
        "chart_revenue": [float(r["total_revenue"]) for r in rows],
    }
    return render(request, "core/reports.html", context)


@role_required(*P.REPORTS)
def report_export(request, kind):
    _form, start, end = _report_range(request)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{kind}_{start}_{end}.csv"'
    writer = csv.writer(response)
    if kind == "daily":
        rows, _summary = reports.daily_stats(start, end)
        writer.writerow(["Date", "Rooms sold", "Occupancy %", "Room revenue", "Other revenue", "Total revenue",
                         "ADR", "RevPAR", "Collected"])
        for r in rows:
            writer.writerow([r["date"], r["rooms_sold"], r["occupancy"], r["room_revenue"], r["other_revenue"],
                             r["total_revenue"], r["adr"], r["revpar"], r["collected"]])
    elif kind == "payments":
        writer.writerow(["Receipt", "Date", "Kind", "Method", "Amount", "Reference", "Booking/Order", "Guest",
                         "Received by", "Notes"])
        qs = reports.payments_in_range(start, end).select_related(
            "booking__guest", "order", "received_by").order_by("created_at")
        for p in qs:
            writer.writerow([
                p.receipt_number, timezone.localtime(p.created_at).strftime("%Y-%m-%d %H:%M"),
                p.get_kind_display(), p.get_method_display(), p.signed_amount, p.reference, p.target_label,
                p.booking.guest if p.booking_id else (p.order.customer_name if p.order_id else ""),
                p.received_by or "", p.notes,
            ])
    elif kind == "bookings":
        writer.writerow(["Reference", "Guest", "Phone", "Room", "Type", "Check-in", "Check-out", "Nights",
                         "Rate", "Status", "Source", "Charges", "Paid", "Balance"])
        qs = (Booking.objects.with_totals().filter(check_in_date__lte=end, check_out_date__gte=start)
              .select_related("guest", "room__room_type").order_by("check_in_date"))
        for b in qs:
            writer.writerow([b.reference, b.guest, b.guest.phone, b.room.number, b.room.room_type, b.check_in_date,
                             b.check_out_date, b.nights, b.rate, b.get_status_display(), b.get_source_display(),
                             b.charges_total, b.payments_total, b.balance])
    else:
        return HttpResponse("Unknown export", status=404)
    return response


@role_required()
def settings_view(request):
    instance, _ = HotelSettings.objects.get_or_create(pk=1)
    form = HotelSettingsForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_action(request.user, "settings.update", instance, "Updated hotel settings")
        messages.success(request, "Settings saved.")
        return redirect("core:settings")
    from django.conf import settings as dj

    from mpesa.services import c2b_urls, stk_callback_url

    mpesa_info = {
        "environment": dj.MPESA_ENVIRONMENT,
        "simulate": dj.MPESA_SIMULATE,
        "shortcode": dj.MPESA_SHORTCODE,
        "transaction_type": dj.MPESA_TRANSACTION_TYPE,
        "till": dj.MPESA_TILL_NUMBER,
        "credentials": bool(dj.MPESA_CONSUMER_KEY and dj.MPESA_CONSUMER_SECRET),
        "callback_url": stk_callback_url(),
        "c2b": c2b_urls(),
        "callback_is_https": stk_callback_url().startswith("https://"),
        "default_token": dj.MPESA_CALLBACK_TOKEN == "change-this-callback-token",
    }
    return render(request, "core/settings.html", {"form": form, "mpesa": mpesa_info})


@role_required(*P.MANAGEMENT)
def audit_log(request):
    qs = AuditLog.objects.select_related("user")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(description__icontains=q)
    action = request.GET.get("action", "")
    if action:
        qs = qs.filter(action__startswith=action)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "core/audit_log.html", {"page": page, "q": q, "action": action})


@role_required(*P.MANAGEMENT)
def branding(request):
    hotel, _ = HotelSettings.objects.get_or_create(pk=1)
    assets = {a.kind: a for a in BrandAsset.objects.defer("data")}
    errors = {}
    is_identity = request.method == "POST" and request.POST.get("action") == "identity"
    identity_form = HotelIdentityForm(request.POST if is_identity else None, instance=hotel, prefix="hotel")
    if is_identity:
        old_name = HotelSettings.objects.get(pk=hotel.pk).name
        if identity_form.is_valid():
            identity_form.save()
            if old_name != hotel.name:
                log_action(request.user, "settings.rename", hotel, f"Renamed hotel from '{old_name}' to '{hotel.name}'")
                messages.success(request, f"Hotel renamed to “{hotel.name}”. The new name now shows everywhere.")
            else:
                messages.success(request, "Hotel name and tagline saved.")
            return redirect("core:branding")
    elif request.method == "POST":
        kind = request.POST.get("kind", "")
        action = request.POST.get("action", "upload")
        if kind not in BrandAsset.Kind.values:
            raise Http404()
        label = BrandAsset.Kind(kind).label
        if action == "remove":
            BrandAsset.objects.filter(kind=kind).delete()
            log_action(request.user, "branding.remove", None, f"Removed {label.lower()}")
            messages.success(request, f"{label} removed.")
            return redirect("core:branding")
        form = LogoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            upload = form.cleaned_data["file"]
            try:
                content_type, data = read_logo(upload, kind)
            except ValidationError as exc:
                errors[kind] = exc.messages[0]
            else:
                BrandAsset.objects.update_or_create(kind=kind, defaults={
                    "content_type": content_type, "data": data, "size": len(data),
                    "filename": upload.name[:150], "updated_by": request.user,
                })
                log_action(request.user, "branding.upload", None, f"Uploaded {label.lower()} ({upload.name})")
                messages.success(request, f"{label} updated. It now shows across the website, staff area and printouts.")
                return redirect("core:branding")
        else:
            errors[kind] = "Choose an image file to upload."
    slots = [
        {"kind": BrandAsset.Kind.LOGO, "asset": assets.get("logo"), "error": errors.get("logo"),
         "help": "Used on the website header, invoices, receipts and bills. A wide PNG or SVG with a transparent "
                 "background works best (around 400 × 120 px)."},
        {"kind": BrandAsset.Kind.LOGO_LIGHT, "asset": assets.get("logo-light"), "error": errors.get("logo-light"),
         "help": "A white or light version for dark backgrounds: website footer, staff sidebar and login screen. "
                 "If you skip it, the main logo is shown on a white badge."},
        {"kind": BrandAsset.Kind.FAVICON, "asset": assets.get("favicon"), "error": errors.get("favicon"),
         "help": "The small square icon in browser tabs and bookmarks. Square PNG (at least 64 × 64 px), ICO or SVG. "
                 "Falls back to the main logo."},
    ]
    return render(request, "core/branding.html", {"slots": slots, "hotel_obj": hotel, "identity_form": identity_form})


def brand_asset(request, kind):
    """Serve an uploaded logo. Public, cache-friendly, and SVGs are sandboxed so they can't run scripts."""
    asset = get_object_or_404(BrandAsset, kind=kind)
    response = HttpResponse(bytes(asset.data), content_type=asset.content_type)
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"
    if request.GET.get("v"):
        response["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        response["Cache-Control"] = "public, max-age=300"
    return response


def permission_denied(request, exception=None):
    return render(request, "403.html", status=403)


def page_not_found(request, exception=None):
    return render(request, "404.html", status=404)
