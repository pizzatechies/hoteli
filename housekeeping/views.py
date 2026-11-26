from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts import permissions as P
from accounts.permissions import role_required
from core.redirects import redirect_back
from bookings.models import Booking
from core.models import log_action
from rooms.models import Room

from . import services
from .forms import HousekeepingTaskForm, MaintenanceForm
from .models import HousekeepingTask, MaintenanceRequest

T = HousekeepingTask


@role_required(*P.HOUSEKEEPING)
def board(request):
    today = timezone.localdate()
    rooms = list(Room.objects.filter(is_active=True).select_related("room_type").order_by("floor", "number"))
    occupied = set(Booking.objects.filter(status=Booking.Status.CHECKED_IN).values_list("room_id", flat=True))
    departing = set(Booking.objects.filter(status=Booking.Status.CHECKED_IN, check_out_date__lte=today)
                    .values_list("room_id", flat=True))
    arriving = set(Booking.objects.filter(status__in=(Booking.Status.PENDING, Booking.Status.CONFIRMED),
                                          check_in_date=today).values_list("room_id", flat=True))
    open_tasks = {}
    for task in T.objects.filter(status__in=(T.Status.PENDING, T.Status.IN_PROGRESS)).select_related("assigned_to"):
        open_tasks.setdefault(task.room_id, []).append(task)
    for room in rooms:
        room.occupied = room.pk in occupied
        room.departing = room.pk in departing
        room.arriving = room.pk in arriving
        room.tasks = open_tasks.get(room.pk, [])
    status_filter = request.GET.get("status", "")
    if status_filter == "dirty":
        rooms = [r for r in rooms if r.hk_status in (Room.HKStatus.DIRTY, Room.HKStatus.CLEANING)]
    elif status_filter == "ready":
        rooms = [r for r in rooms if r.is_ready]
    elif status_filter == "ooo":
        rooms = [r for r in rooms if r.is_out_of_order]
    my_tasks = T.objects.filter(assigned_to=request.user, status__in=(T.Status.PENDING, T.Status.IN_PROGRESS)
                                ).select_related("room")
    return render(request, "housekeeping/board.html", {
        "rooms": rooms, "my_tasks": my_tasks, "status_filter": status_filter, "statuses": Room.HKStatus.choices,
    })


@role_required(*P.HOUSEKEEPING)
@require_POST
def room_status(request, pk):
    room = get_object_or_404(Room, pk=pk)
    status = request.POST.get("status")
    if status in Room.HKStatus.values:
        services.set_room_status(room, status, request.user)
        messages.success(request, f"Room {room.number} marked {room.get_hk_status_display().lower()}.")
    return redirect_back(request, "housekeeping:board")


@role_required(*P.HOUSEKEEPING)
def task_list(request):
    qs = T.objects.select_related("room", "assigned_to", "booking")
    status = request.GET.get("status", "open")
    if status == "open":
        qs = qs.filter(status__in=(T.Status.PENDING, T.Status.IN_PROGRESS))
    elif status:
        qs = qs.filter(status=status)
    if request.GET.get("mine"):
        qs = qs.filter(assigned_to=request.user)
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(request, "housekeeping/task_list.html", {
        "page": page, "status": status, "statuses": T.Status.choices, "mine": request.GET.get("mine", ""),
    })


@role_required(*P.HOUSEKEEPING)
def task_form(request, pk=None):
    task = get_object_or_404(T, pk=pk) if pk else None
    initial = {"due_date": timezone.localdate()}
    if request.GET.get("room"):
        initial["room"] = request.GET["room"]
    form = HousekeepingTaskForm(request.POST or None, instance=task, initial=initial)
    if request.method == "POST" and form.is_valid():
        task = form.save(commit=False)
        if not task.pk:
            task.created_by = request.user
        task.save()
        log_action(request.user, "housekeeping.task", task, f"Saved task {task}")
        messages.success(request, "Task saved.")
        return redirect("housekeeping:tasks")
    return render(request, "housekeeping/form.html", {"form": form, "title": "Edit task" if task else "New task"})


@role_required(*P.HOUSEKEEPING)
@require_POST
def task_action(request, pk, action):
    task = get_object_or_404(T, pk=pk)
    if action == "start":
        services.start_task(task, request.user)
        messages.success(request, f"Started: {task}.")
    elif action == "done":
        services.complete_task(task, request.user)
        messages.success(request, f"Completed: {task}.")
    elif action == "cancel":
        task.status = T.Status.CANCELLED
        task.save(update_fields=["status"])
        messages.success(request, "Task cancelled.")
    elif action == "claim":
        task.assigned_to = request.user
        task.save(update_fields=["assigned_to"])
        messages.success(request, "Task assigned to you.")
    return redirect_back(request, "housekeeping:tasks")


@role_required(*P.HOUSEKEEPING)
def maintenance_list(request):
    qs = MaintenanceRequest.objects.select_related("room", "assigned_to", "reported_by")
    status = request.GET.get("status", "open")
    if status == "open":
        qs = qs.filter(status__in=MaintenanceRequest.OPEN_STATUSES)
    elif status:
        qs = qs.filter(status=status)
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(request, "housekeeping/maintenance_list.html", {
        "page": page, "status": status, "statuses": MaintenanceRequest.Status.choices,
    })


@role_required(*P.HOUSEKEEPING)
def maintenance_form(request, pk=None):
    item = get_object_or_404(MaintenanceRequest, pk=pk) if pk else None
    initial = {}
    if request.GET.get("room"):
        initial["room"] = request.GET["room"]
    form = MaintenanceForm(request.POST or None, instance=item, initial=initial)
    old_room = item.room if item else None
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        if not item.pk:
            item.reported_by = request.user
        if item.status == MaintenanceRequest.Status.RESOLVED and not item.resolved_at:
            item.resolved_at = timezone.now()
        item.save()
        services.sync_room_out_of_order(item.room)
        if old_room and old_room != item.room:
            services.sync_room_out_of_order(old_room)
        log_action(request.user, "maintenance.save", item, f"{item} – {item.get_status_display()}")
        messages.success(request, "Maintenance request saved.")
        if item.puts_room_out_of_order and item.is_open:
            affected = list(services.affected_bookings(item.room))
            if affected:
                refs = ", ".join(f"{b.reference} ({b.guest})" for b in affected[:5])
                messages.warning(
                    request,
                    f"Room {item.room.number} is out of order but has upcoming/in-house bookings: {refs}. "
                    "Move them to another room.",
                )
        return redirect("housekeeping:maintenance")
    return render(request, "housekeeping/form.html", {
        "form": form, "title": f"Maintenance: {item}" if item else "Report maintenance issue",
    })
