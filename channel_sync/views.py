from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts import permissions as P
from accounts.permissions import role_required
from core.models import log_action

from . import ical, services
from .forms import ChannelCalendarForm, RoomBlockForm
from .models import ChannelCalendar, RoomBlock


def feed(request, token):
    """Public, unguessable per-room availability feed for the other site to import."""
    calendar = get_object_or_404(ChannelCalendar.objects.select_related("room"), export_token=token, is_active=True)
    body = ical.build_calendar(f"Room {calendar.room.number}", services.export_events(calendar))
    response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = f'inline; filename="room-{calendar.room.number}.ics"'
    response["Cache-Control"] = "no-cache"
    return response


@role_required(*P.MANAGEMENT, *P.FRONT_DESK)
def channel_list(request):
    calendars = ChannelCalendar.objects.select_related("room", "room__room_type")
    for c in calendars:
        c.feed_url = settings.SITE_URL + reverse("channel_sync:feed", args=[c.export_token])
    today = timezone.localdate()
    blocks = RoomBlock.objects.filter(end_date__gt=today).select_related("room", "calendar")
    return render(request, "channel_sync/list.html", {
        "calendars": calendars, "blocks": blocks[:60], "conflicts": blocks.exclude(conflict=""),
        "block_form": RoomBlockForm(), "can_manage": request.user.has_role(*P.MANAGEMENT),
    })


@role_required(*P.MANAGEMENT)
def calendar_form(request, pk=None):
    calendar = get_object_or_404(ChannelCalendar, pk=pk) if pk else None
    form = ChannelCalendarForm(request.POST or None, instance=calendar)
    if request.method == "POST":
        if request.POST.get("delete") and calendar:
            calendar.delete()
            messages.success(request, "Calendar link removed (its imported blocks were removed too).")
            return redirect("channel_sync:list")
        if form.is_valid():
            calendar = form.save()
            log_action(request.user, "channels.save", calendar, f"Saved calendar {calendar}")
            messages.success(request, f"Saved. Give {calendar.name} this room's export link from the Channels page.")
            return redirect("channel_sync:list")
    return render(request, "rooms/form.html", {
        "form": form, "title": f"Edit {calendar}" if calendar else "Connect a room to Booking.com, Airbnb…",
        "can_delete": bool(calendar),
        "help": "Create one entry per room per site. Paste the other site's iCal export link so its reservations "
                "block the room here; then copy this room's export link into the other site.",
    })


@role_required(*P.MANAGEMENT, *P.FRONT_DESK)
@require_POST
def sync_now(request, pk=None):
    calendars = [get_object_or_404(ChannelCalendar, pk=pk)] if pk else list(
        ChannelCalendar.objects.filter(is_active=True).exclude(import_url=""))
    ok = failed = 0
    for calendar in calendars:
        if not calendar.import_url:
            continue
        try:
            services.sync_calendar(calendar, user=request.user)
            ok += 1
        except ical.CalendarError as exc:
            failed += 1
            messages.error(request, f"{calendar}: {exc}")
    if ok:
        messages.success(request, f"Synced {ok} calendar{'s' if ok != 1 else ''}.")
    if not ok and not failed:
        messages.info(request, "Nothing to sync yet. Add the other site's calendar link first.")
    return redirect("channel_sync:list")


@role_required(*P.FRONT_DESK)
@require_POST
def block_create(request):
    form = RoomBlockForm(request.POST)
    if form.is_valid():
        block = form.save()
        log_action(request.user, "channels.block", block, f"Blocked {block}")
        messages.success(request, f"Room {block.room.number} blocked {block.start_date:%d %b} – {block.end_date:%d %b}.")
    else:
        messages.error(request, "Block not saved: " + "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect("channel_sync:list")


@role_required(*P.FRONT_DESK)
@require_POST
def block_delete(request, pk):
    block = get_object_or_404(RoomBlock, pk=pk, calendar__isnull=True)
    block.delete()
    messages.success(request, "Block removed.")
    return redirect("channel_sync:list")
