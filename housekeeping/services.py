from django.db import transaction
from django.utils import timezone

from core.models import log_action
from rooms.models import Room

from .models import HousekeepingTask, MaintenanceRequest

T = HousekeepingTask


def create_checkout_task(room, booking=None, user=None, note=""):
    """Queue a clean after departure. Urgent if someone arrives in this room today."""
    from bookings.models import Booking

    if T.objects.filter(room=room, task_type=T.TaskType.CHECKOUT_CLEAN,
                        status__in=(T.Status.PENDING, T.Status.IN_PROGRESS)).exists():
        return None
    today = timezone.localdate()
    arriving = Booking.objects.filter(
        room=room, check_in_date=today, status__in=(Booking.Status.PENDING, Booking.Status.CONFIRMED)
    ).exists()
    return T.objects.create(
        room=room, booking=booking, task_type=T.TaskType.CHECKOUT_CLEAN, due_date=today,
        priority=T.Priority.URGENT if arriving else T.Priority.HIGH,
        notes=(note or "") + (" Guest arriving today." if arriving else ""),
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )


def set_room_status(room, status, user=None):
    old = room.get_hk_status_display()
    room.hk_status = status
    room.save(update_fields=["hk_status"])
    log_action(user, "room.status", room, f"Room {room.number}: {old} → {room.get_hk_status_display()}")
    return room


def start_task(task, user=None):
    if task.status != T.Status.PENDING:
        return task
    task.status = T.Status.IN_PROGRESS
    task.started_at = timezone.now()
    if task.assigned_to is None and getattr(user, "is_authenticated", False):
        task.assigned_to = user
    task.save()
    if task.task_type in T.CLEANING_TYPES:
        Room.objects.filter(pk=task.room_id).update(hk_status=Room.HKStatus.CLEANING)
    return task


def complete_task(task, user=None):
    if not task.is_open:
        return task
    with transaction.atomic():
        task.status = T.Status.DONE
        task.completed_at = timezone.now()
        if task.started_at is None:
            task.started_at = task.completed_at
        if task.assigned_to is None and getattr(user, "is_authenticated", False):
            task.assigned_to = user
        task.save()
        if task.task_type in T.CLEANING_TYPES:
            Room.objects.filter(pk=task.room_id).update(hk_status=Room.HKStatus.CLEAN)
        elif task.task_type == T.TaskType.INSPECTION:
            Room.objects.filter(pk=task.room_id).update(hk_status=Room.HKStatus.INSPECTED)
        log_action(user, "housekeeping.done", task, f"{task} completed")
    return task


def sync_room_out_of_order(room):
    """Keep the room's out-of-order flag in line with its open maintenance requests."""
    if room is None:
        return
    blocking = room.maintenance_requests.filter(
        puts_room_out_of_order=True, status__in=MaintenanceRequest.OPEN_STATUSES
    ).order_by("-created_at").first()
    if blocking:
        room.is_out_of_order = True
        room.out_of_order_reason = blocking.title[:200]
        room.save(update_fields=["is_out_of_order", "out_of_order_reason"])
    elif room.is_out_of_order and room.maintenance_requests.filter(puts_room_out_of_order=True).exists():
        room.is_out_of_order = False
        room.out_of_order_reason = ""
        room.save(update_fields=["is_out_of_order", "out_of_order_reason"])


def affected_bookings(room):
    """Upcoming bookings in a room that is being taken out of order."""
    from bookings.models import Booking

    if room is None:
        return Booking.objects.none()
    return Booking.objects.filter(
        room=room, status__in=Booking.ACTIVE_STATUSES, check_out_date__gt=timezone.localdate()
    ).select_related("guest")
