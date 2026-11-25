from django import forms

from bookings.models import Booking
from core.forms import BootstrapMixin

from .models import MenuCategory, MenuItem, Order


def in_house_bookings():
    return Booking.objects.filter(status=Booking.Status.CHECKED_IN).select_related("guest", "room")


class OrderForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Order
        fields = ["outlet", "table_number", "booking", "customer_name", "discount", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["booking"].queryset = in_house_bookings()
        self.fields["booking"].label = "In-house guest (room)"
        self.fields["booking"].label_from_instance = lambda b: f"Room {b.room.number} – {b.guest} ({b.reference})"
        self.fields["discount"].required = False

    def clean_discount(self):
        return self.cleaned_data.get("discount") or 0


class MenuCategoryForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = MenuCategory
        fields = ["name", "display_order", "is_active"]


class MenuItemForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = MenuItem
        fields = ["category", "name", "description", "kind", "price", "is_available"]
