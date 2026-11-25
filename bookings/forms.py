from decimal import Decimal

from django import forms
from django.utils import timezone

from core.forms import BootstrapMixin, DateInput
from rooms.models import Room

from .models import Booking, Charge, Guest, Payment


class GuestForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Guest
        fields = [
            "first_name", "last_name", "phone", "email", "id_type", "id_number", "nationality",
            "date_of_birth", "gender", "address", "company", "vehicle_registration",
            "is_vip", "is_blacklisted", "blacklist_reason", "notes",
        ]
        widgets = {"date_of_birth": DateInput(), "notes": forms.Textarea(attrs={"rows": 2})}

    def clean_phone(self):
        from mpesa.utils import normalize_phone

        phone = self.cleaned_data["phone"].strip()
        try:
            normalize_phone(phone)
        except ValueError:
            if not phone.startswith("+"):
                raise forms.ValidationError(
                    "Enter a Kenyan mobile number (0712 345 678) or an international number starting with +."
                )
        return phone

    def clean(self):
        data = super().clean()
        if data.get("is_blacklisted") and not data.get("blacklist_reason"):
            self.add_error("blacklist_reason", "Give a reason for blacklisting this guest.")
        return data


class BookingForm(BootstrapMixin, forms.Form):
    """Reservation form. Either pick an existing guest or fill in the new-guest fields."""

    guest = forms.ModelChoiceField(queryset=Guest.objects.all(), required=False, widget=forms.HiddenInput)
    first_name = forms.CharField(max_length=60, required=False)
    last_name = forms.CharField(max_length=60, required=False)
    phone = forms.CharField(max_length=20, required=False)
    email = forms.EmailField(required=False)
    id_type = forms.ChoiceField(choices=Guest.IDType.choices, required=False, initial=Guest.IDType.NATIONAL_ID)
    id_number = forms.CharField(max_length=40, required=False, label="ID / passport number")
    nationality = forms.CharField(max_length=60, required=False, initial="Kenyan")

    check_in_date = forms.DateField(widget=DateInput(), label="Check-in")
    check_out_date = forms.DateField(widget=DateInput(), label="Check-out")
    adults = forms.IntegerField(min_value=1, max_value=20, initial=1)
    children = forms.IntegerField(min_value=0, max_value=20, initial=0)
    room = forms.ModelChoiceField(queryset=Room.objects.filter(is_active=True).select_related("room_type"))
    rate = forms.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0"), required=False,
        label="Rate per night", help_text="Leave blank to use the room type rate for these dates.",
    )
    source = forms.ChoiceField(choices=Booking.Source.choices, initial=Booking.Source.WALK_IN)
    status = forms.ChoiceField(
        choices=[(Booking.Status.CONFIRMED, "Confirmed"), (Booking.Status.PENDING, "Pending (tentative)")],
        initial=Booking.Status.CONFIRMED,
    )
    special_requests = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)
    internal_notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def __init__(self, *args, editing=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.editing = editing
        self.fields["room"].label_from_instance = lambda r: f"{r.number} – {r.room_type.name}"
        if editing is not None:
            for name in ("guest", "first_name", "last_name", "phone", "email", "id_type", "id_number",
                         "nationality", "status"):
                self.fields.pop(name)
            if editing.status == Booking.Status.CHECKED_IN:
                self.fields["check_in_date"].disabled = True

    def clean(self):
        data = super().clean()
        if self.editing is None and not data.get("guest"):
            for name in ("first_name", "last_name", "phone"):
                if not data.get(name):
                    self.add_error(name, "Required for a new guest (or search for an existing guest).")
        ci, co = data.get("check_in_date"), data.get("check_out_date")
        if ci and co and co <= ci:
            self.add_error("check_out_date", "Check-out must be after check-in.")
        if ci and self.editing is None and ci < timezone.localdate():
            self.add_error("check_in_date", "Check-in cannot be in the past.")
        return data


class ChargeForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Charge
        fields = ["category", "description", "quantity", "unit_price", "service_date"]
        widgets = {"service_date": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].choices = [c for c in Charge.Category.choices if c[0] != Charge.Category.ROOM]
        self.fields["unit_price"].label = "Unit price"


class PaymentForm(BootstrapMixin, forms.Form):
    method = forms.ChoiceField(choices=Payment.Method.choices)
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    reference = forms.CharField(
        max_length=60, required=False, help_text="M-Pesa code, card approval code or bank reference"
    )
    notes = forms.CharField(max_length=255, required=False)

    def clean(self):
        data = super().clean()
        if data.get("method") in (Payment.Method.MPESA, Payment.Method.BANK, Payment.Method.CHEQUE) and not data.get(
            "reference"
        ):
            self.add_error("reference", "A reference is required for this payment method.")
        return data


class RefundForm(BootstrapMixin, forms.Form):
    method = forms.ChoiceField(choices=Payment.Method.choices)
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    reference = forms.CharField(max_length=60, required=False)
    notes = forms.CharField(max_length=255, label="Reason")


class MpesaPromptForm(BootstrapMixin, forms.Form):
    phone = forms.CharField(max_length=20, help_text="Safaricom number that will receive the PIN prompt")
    amount = forms.DecimalField(max_digits=12, decimal_places=0, min_value=Decimal("1"), max_value=Decimal("250000"))


class CancelForm(BootstrapMixin, forms.Form):
    reason = forms.CharField(max_length=255)
    fee = forms.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0"), required=False, label="Cancellation fee"
    )


class VoidForm(BootstrapMixin, forms.Form):
    reason = forms.CharField(max_length=200)
