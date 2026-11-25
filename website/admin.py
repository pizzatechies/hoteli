from django.contrib import admin

from .models import ContactMessage, Facility, WebsiteContent

admin.site.register(WebsiteContent)
admin.site.register(Facility)


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "name", "subject", "is_read")
    list_filter = ("is_read",)
