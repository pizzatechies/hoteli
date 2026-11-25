from django.contrib import admin

from .models import AuditLog, HotelSettings


@admin.register(HotelSettings)
class HotelSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not HotelSettings.objects.exists()


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "description")
    list_filter = ("action",)
    search_fields = ("description", "object_id")
    readonly_fields = [f.name for f in AuditLog._meta.fields]
