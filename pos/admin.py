from django.contrib import admin

from .models import MenuCategory, MenuItem, Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "outlet", "status", "booking", "created_at")
    list_filter = ("outlet", "status")
    inlines = [OrderItemInline]


admin.site.register(MenuCategory)
admin.site.register(MenuItem)
