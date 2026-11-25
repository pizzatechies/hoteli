from django.conf import settings
from django.db import models


class HousekeepingTask(models.Model):
    class TaskType(models.TextChoices):
        CHECKOUT_CLEAN = "CHECKOUT_CLEAN", "Check-out clean"
        STAYOVER_CLEAN = "STAYOVER_CLEAN", "Stay-over service"
        DEEP_CLEAN = "DEEP_CLEAN", "Deep clean"
        TURNDOWN = "TURNDOWN", "Turndown"
        LINEN_CHANGE = "LINEN_CHANGE", "Linen change"
        INSPECTION = "INSPECTION", "Inspection"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        DONE = "DONE", "Done"
        CANCELLED = "CANCELLED", "Cancelled"

    class Priority(models.TextChoices):
        NORMAL = "NORMAL", "Normal"
        HIGH = "HIGH", "High"
        URGENT = "URGENT", "Urgent"

    CLEANING_TYPES = (TaskType.CHECKOUT_CLEAN, TaskType.STAYOVER_CLEAN, TaskType.DEEP_CLEAN)

    room = models.ForeignKey("rooms.Room", on_delete=models.CASCADE, related_name="hk_tasks")
    task_type = models.CharField(max_length=20, choices=TaskType.choices, default=TaskType.CHECKOUT_CLEAN)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="hk_tasks"
    )
    booking = models.ForeignKey(
        "bookings.Booking", null=True, blank=True, on_delete=models.SET_NULL, related_name="hk_tasks"
    )
    due_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["status", "-priority", "created_at"]

    def __str__(self):
        return f"{self.get_task_type_display()} – {self.room}"

    @property
    def is_open(self):
        return self.status in (self.Status.PENDING, self.Status.IN_PROGRESS)


class MaintenanceRequest(models.Model):
    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        URGENT = "URGENT", "Urgent"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        RESOLVED = "RESOLVED", "Resolved"
        CANCELLED = "CANCELLED", "Cancelled"

    OPEN_STATUSES = (Status.OPEN, Status.IN_PROGRESS)

    room = models.ForeignKey(
        "rooms.Room", null=True, blank=True, on_delete=models.CASCADE, related_name="maintenance_requests"
    )
    location = models.CharField(max_length=120, blank=True, help_text="For common areas, e.g. Lobby, Kitchen")
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True)
    puts_room_out_of_order = models.BooleanField(
        "Take room out of order", default=False, help_text="Block the room from sale until resolved."
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="maintenance_assignments",
    )
    cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    resolution_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        where = self.room or self.location or "General"
        return f"{self.title} ({where})"

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES
