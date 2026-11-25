from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts import permissions as P
from accounts.permissions import role_required
from bookings.models import Booking
from core.models import log_action

from .forms import RoomForm, RoomTypeForm, SeasonalRateForm
from .models import Room, RoomType, SeasonalRate


@role_required(*P.BOOKING_VIEW, *P.HOUSEKEEPING)
def room_list(request):
    today = timezone.localdate()
    rooms = Room.objects.select_related("room_type").order_by("floor", "number")
    occupants = {
        b.room_id: b for b in Booking.objects.filter(status=Booking.Status.CHECKED_IN).select_related("guest")
    }
    arrivals = set(
        Booking.objects.filter(status__in=(Booking.Status.PENDING, Booking.Status.CONFIRMED),
                               check_in_date=today).values_list("room_id", flat=True)
    )
    floor_map = {}
    for room in rooms:
        room.occupant = occupants.get(room.pk)
        room.arriving = room.pk in arrivals
        floor_map.setdefault(room.floor or "—", []).append(room)
    return render(request, "rooms/room_list.html", {
        "floors": floor_map.items(), "total": rooms.count(),
        "can_manage": request.user.has_role(*P.MANAGEMENT),
    })


@role_required(*P.MANAGEMENT)
def room_form(request, pk=None):
    room = get_object_or_404(Room, pk=pk) if pk else None
    form = RoomForm(request.POST or None, instance=room)
    if request.method == "POST" and form.is_valid():
        room = form.save()
        log_action(request.user, "room.save", room)
        messages.success(request, f"{room} saved.")
        return redirect("rooms:list")
    return render(request, "rooms/form.html", {"form": form, "title": f"Edit {room}" if room else "Add room"})


@role_required(*P.MANAGEMENT)
def room_type_list(request):
    types = RoomType.objects.annotate(
        room_count=Count("rooms", filter=Q(rooms__is_active=True))
    ).prefetch_related("seasonal_rates")
    return render(request, "rooms/room_type_list.html", {
        "types": types, "seasons": SeasonalRate.objects.select_related("room_type"),
    })


@role_required(*P.MANAGEMENT)
def room_type_form(request, pk=None):
    rt = get_object_or_404(RoomType, pk=pk) if pk else None
    form = RoomTypeForm(request.POST or None, instance=rt)
    if request.method == "POST" and form.is_valid():
        rt = form.save()
        log_action(request.user, "room_type.save", rt)
        messages.success(request, f"Room type {rt} saved.")
        return redirect("rooms:types")
    return render(request, "rooms/form.html", {"form": form, "title": f"Edit {rt}" if rt else "Add room type"})


@role_required(*P.MANAGEMENT)
def season_form(request, pk=None):
    season = get_object_or_404(SeasonalRate, pk=pk) if pk else None
    form = SeasonalRateForm(request.POST or None, instance=season)
    if request.method == "POST":
        if request.POST.get("delete") and season:
            season.delete()
            messages.success(request, "Seasonal rate deleted.")
            return redirect("rooms:types")
        if form.is_valid():
            season = form.save()
            log_action(request.user, "season.save", season)
            messages.success(request, "Seasonal rate saved.")
            return redirect("rooms:types")
    return render(request, "rooms/form.html", {
        "form": form, "title": "Edit seasonal rate" if season else "Add seasonal rate", "can_delete": bool(season),
    })
