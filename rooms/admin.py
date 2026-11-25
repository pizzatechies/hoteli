from django.contrib import admin

from .models import Room, RoomType, SeasonalRate


class SeasonalRateInline(admin.TabularInline):
    model = SeasonalRate
    extra = 0


@admin.register(RoomType)
class RoomTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "base_rate", "max_adults", "max_children", "is_active")
    inlines = [SeasonalRateInline]


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("number", "room_type", "floor", "hk_status", "is_out_of_order", "is_active")
    list_filter = ("room_type", "hk_status", "is_out_of_order")
