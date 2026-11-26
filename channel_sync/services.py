import logging

from django.db import transaction
from django.utils import timezone

from core.models import log_action

from . import ical
from .models import ChannelCalendar, RoomBlock

logger = logging.getLogger("bookings")


def blocks_overlapping(check_in, check_out):
    return RoomBlock.objects.filter(start_date__lt=check_out, end_date__gt=check_in)


def sync_calendar(calendar, user=None):
    """Import one outside calendar. Returns (created, updated, removed). Raises CalendarError."""
    from bookings.models import Booking

    try:
        text = ical.fetch(calendar.import_url)
        events = [e for e in ical.parse_events(text) if e["end"] > timezone.localdate()]
    except ical.CalendarError as exc:
        calendar.last_error = str(exc)[:255]
        calendar.last_synced_at = timezone.now()
        calendar.save(update_fields=["last_error", "last_synced_at"])
        raise
    created = updated = 0
    seen = set()
    with transaction.atomic():
        for event in events:
            seen.add(event["uid"])
            block, is_new = RoomBlock.objects.update_or_create(
                calendar=calendar, external_uid=event["uid"],
                defaults={"room": calendar.room, "start_date": event["start"], "end_date": event["end"],
                          "summary": event["summary"] or f"{calendar.name} reservation"},
            )
            clash = (Booking.objects.active().overlapping(block.start_date, block.end_date)
                     .filter(room=calendar.room).first())
            block.conflict = (f"Overlaps booking {clash.reference} ({clash.guest}) – move one of them"
                              if clash else "")[:255]
            block.save(update_fields=["conflict"])
            created += is_new
            updated += not is_new
        stale = calendar.blocks.exclude(external_uid__in=seen)
        removed = stale.count()
        stale.delete()  # cancelled on the other site
        calendar.last_error = ""
        calendar.last_synced_at = timezone.now()
        calendar.events_imported = len(seen)
        calendar.save(update_fields=["last_error", "last_synced_at", "events_imported"])
    if user is not None:
        log_action(user, "channels.sync", calendar, f"Synced {calendar}: {created} new, {removed} removed")
    return created, updated, removed


def sync_all():
    results = []
    for calendar in ChannelCalendar.objects.filter(is_active=True).exclude(import_url="").select_related("room"):
        try:
            results.append((calendar, sync_calendar(calendar), ""))
        except ical.CalendarError as exc:
            logger.warning("Calendar sync failed for %s: %s", calendar, exc)
            results.append((calendar, None, str(exc)))
    return results


def export_events(calendar):
    """What this room's feed tells the other site: our bookings, manual blocks and other sites' blocks."""
    from bookings.models import Booking

    today = timezone.localdate()
    events = []
    for b in Booking.objects.active().filter(room=calendar.room, check_out_date__gt=today):
        events.append((f"booking-{b.reference}@hoteli", b.check_in_date, b.check_out_date, "Reserved"))
    for block in RoomBlock.objects.filter(room=calendar.room, end_date__gt=today).exclude(calendar=calendar):
        events.append((f"block-{block.pk}@hoteli", block.start_date, block.end_date, "Not available"))
    return events
