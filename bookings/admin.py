from django.contrib import admin

from .models import Booking, Charge, Guest, NightAuditRun, Payment


@admin.register(Guest)
class GuestAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone", "email", "id_number", "is_vip", "is_blacklisted")
    search_fields = ("first_name", "last_name", "phone", "email", "id_number")


class ChargeInline(admin.TabularInline):
    model = Charge
    extra = 0
    readonly_fields = ("amount",)


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fk_name = "booking"


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("reference", "guest", "room", "check_in_date", "check_out_date", "status", "source")
    list_filter = ("status", "source")
    search_fields = ("reference", "guest__first_name", "guest__last_name", "guest__phone")
    inlines = [ChargeInline, PaymentInline]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("receipt_number", "created_at", "method", "kind", "amount", "reference", "is_void")
    list_filter = ("method", "kind", "is_void")
    search_fields = ("receipt_number", "reference")


admin.site.register(NightAuditRun)
