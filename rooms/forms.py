from django import forms

from core.forms import BootstrapMixin, DateInput

from .models import CorporateAccount, PromoCode, Room, RoomType, SeasonalRate, StayDiscount


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


class PromoCodeForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = PromoCode
        fields = ["code", "description", "percent_off", "amount_off", "room_types", "min_nights", "valid_from",
                  "valid_until", "max_uses", "on_website", "is_active"]
        widgets = {"valid_from": DateInput(), "valid_until": DateInput(),
                   "room_types": forms.CheckboxSelectMultiple}


class StayDiscountForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = StayDiscount
        fields = ["min_nights", "percent_off", "room_type", "is_active"]


class CorporateAccountForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = CorporateAccount
        fields = ["name", "percent_off", "contact_name", "email", "phone", "kra_pin", "notes", "is_active"]
