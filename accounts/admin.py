from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class HotelUserAdmin(UserAdmin):
    list_display = ("username", "first_name", "last_name", "role", "is_active", "last_login")
    list_filter = ("role", "is_active", "is_superuser")
    fieldsets = UserAdmin.fieldsets + (("Hotel", {"fields": ("role", "phone")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Hotel", {"fields": ("role", "phone")}),)
