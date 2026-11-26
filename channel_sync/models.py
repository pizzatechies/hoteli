import uuid

from django.db import models


class ChannelCalendar(models.Model):
    """One room's listing on an outside site (Booking.com, Airbnb, Expedia…), synced via iCal."""

    room = models.ForeignKey("rooms.Room", on_delete=models.CASCADE, related_name="channel_calendars")
    name = models.CharField(max_length=60, help_text="e.g. Booking.com, Airbnb")
    import_url = models.URLField(
        "Their calendar link (iCal)", max_length=600, blank=True,
        help_text="Paste the .ics export link from the other site so its reservations block this room here.",
    )
    export_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    is_active = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=255, blank=True)
    events_imported = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["room__number", "name"]
        unique_together = [("room", "name")]

    def __str__(self):
        return f"{self.name} – room {self.room.number}"


class RoomBlock(models.Model):
    """Dates a room is unavailable without a booking here (imported OTA reservations or manual blocks)."""

    room = models.ForeignKey("rooms.Room", on_delete=models.CASCADE, related_name="blocks")
    start_date = models.DateField()
    end_date = models.DateField(help_text="Like a check-out date: the room is free again on this day.")
    calendar = models.ForeignKey(ChannelCalendar, null=True, blank=True, on_delete=models.CASCADE,
                                 related_name="blocks")
    external_uid = models.CharField(max_length=255, blank=True)
    summary = models.CharField(max_length=200, blank=True)
    conflict = models.CharField(max_length=255, blank=True, help_text="Set when it overlaps a booking made here.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_date", "room__number"]
        constraints = [
            models.UniqueConstraint(fields=["calendar", "external_uid"], name="unique_block_per_calendar_event",
                                    condition=~models.Q(external_uid="")),
            models.CheckConstraint(condition=models.Q(end_date__gt=models.F("start_date")), name="block_end_after_start"),
        ]

    def __str__(self):
        return f"Room {self.room.number} blocked {self.start_date}–{self.end_date}"

    @property
    def source(self):
        return self.calendar.name if self.calendar_id else "Manual block"
