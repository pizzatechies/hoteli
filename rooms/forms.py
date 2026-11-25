from django import forms

from core.forms import BootstrapMixin, DateInput

from .models import Room, RoomType, SeasonalRate


class RoomTypeForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = RoomType
        fields = ["name", "description", "base_rate", "max_adults", "max_children", "bed_type", "size_sqm",
                  "amenities", "image_url", "display_order", "is_active"]


class RoomForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Room
        fields = ["number", "room_type", "floor", "hk_status", "is_out_of_order", "out_of_order_reason",
                  "is_active", "notes"]

    def clean(self):
        data = super().clean()
        if data.get("is_out_of_order") and not data.get("out_of_order_reason"):
            self.add_error("out_of_order_reason", "Say why the room is out of order.")
        return data


class SeasonalRateForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = SeasonalRate
        fields = ["room_type", "name", "start_date", "end_date", "rate", "priority"]
        widgets = {"start_date": DateInput(), "end_date": DateInput()}
