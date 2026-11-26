from django.contrib import admin

from .models import SmsMessage


@admin.register(SmsMessage)
class SmsMessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "to", "kind", "status", "attempts")
    list_filter = ("status", "kind")
    search_fields = ("to", "body")
