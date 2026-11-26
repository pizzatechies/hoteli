import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class RoomType(models.Model):
    name = models.CharField(max_length=80, unique=True)
    description = models.TextField(blank=True)
    base_rate = models.DecimalField(
        "Rate per night", max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    max_adults = models.PositiveSmallIntegerField(default=2, validators=[MinValueValidator(1)])
    max_children = models.PositiveSmallIntegerField(default=0)
    bed_type = models.CharField(max_length=60, blank=True, default="Queen bed")
    size_sqm = models.PositiveIntegerField("Size (m²)", null=True, blank=True)
    amenities = models.CharField(
        max_length=500, blank=True, help_text="Comma separated, e.g. Wi-Fi, TV, Air conditioning"
    )
    image_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True, help_text="Inactive types are hidden from bookings.")
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "base_rate", "name"]

    def __str__(self):
        return self.name

    @property
    def amenity_list(self):
        return [a.strip() for a in self.amenities.split(",") if a.strip()]

    @property
    def max_occupancy(self):
        return self.max_adults + self.max_children

    def rate_for(self, date):
        """Nightly rate on ``date``: the highest-priority seasonal rate, else the base rate."""
        season = (
            self.seasonal_rates.filter(start_date__lte=date, end_date__gte=date)
            .order_by("-priority", "-id")
            .first()
        )
        return season.rate if season else self.base_rate

    def quote(self, check_in, check_out):
        """Total for the stay using per-night (seasonal) rates."""
        total = Decimal("0")
        day = check_in
        while day < check_out:
            total += self.rate_for(day)
            day += datetime.timedelta(days=1)
        return total


class SeasonalRate(models.Model):
    room_type = models.ForeignKey(RoomType, on_delete=models.CASCADE, related_name="seasonal_rates")
    name = models.CharField(max_length=80, help_text="e.g. Christmas peak, Low season")
    start_date = models.DateField()
    end_date = models.DateField(help_text="Inclusive")
    rate = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    priority = models.PositiveSmallIntegerField(default=0, help_text="Higher wins when seasons overlap.")

    class Meta:
        ordering = ["start_date"]

    def __str__(self):
        return f"{self.room_type} – {self.name}"

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "End date must be on or after the start date."})


class Room(models.Model):
    class HKStatus(models.TextChoices):
        CLEAN = "CLEAN", "Clean"
        DIRTY = "DIRTY", "Dirty"
        CLEANING = "CLEANING", "Cleaning in progress"
        INSPECTED = "INSPECTED", "Inspected"

    number = models.CharField(max_length=10, unique=True)
    room_type = models.ForeignKey(RoomType, on_delete=models.PROTECT, related_name="rooms")
    floor = models.CharField(max_length=20, blank=True)
    hk_status = models.CharField(
        "Housekeeping status", max_length=12, choices=HKStatus.choices, default=HKStatus.CLEAN
    )
    is_out_of_order = models.BooleanField(default=False)
    out_of_order_reason = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True, help_text="Inactive rooms are excluded from inventory.")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["floor", "number"]

    def __str__(self):
        return f"Room {self.number}"

    @property
    def is_ready(self):
        return self.hk_status in (self.HKStatus.CLEAN, self.HKStatus.INSPECTED) and not self.is_out_of_order

    def current_booking(self):
        from bookings.models import Booking

        return self.bookings.filter(status=Booking.Status.CHECKED_IN).select_related("guest").first()


class PromoCode(models.Model):
    """Discount code guests enter on the website (or staff apply to a booking)."""

    code = models.CharField(max_length=30, unique=True, help_text="What guests type, e.g. KARIBU10")
    description = models.CharField(max_length=150, blank=True)
    percent_off = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True,
                                      validators=[MinValueValidator(Decimal("0.01"))])
    amount_off = models.DecimalField("KES off the stay", max_digits=10, decimal_places=2, null=True, blank=True,
                                     validators=[MinValueValidator(Decimal("1"))])
    room_types = models.ManyToManyField(RoomType, blank=True, help_text="Leave empty for all room types.")
    min_nights = models.PositiveSmallIntegerField(default=1)
    valid_from = models.DateField(null=True, blank=True, help_text="First check-in date the code applies to.")
    valid_until = models.DateField(null=True, blank=True, help_text="Last check-in date the code applies to.")
    max_uses = models.PositiveIntegerField(null=True, blank=True, help_text="Blank = unlimited.")
    times_used = models.PositiveIntegerField(default=0, editable=False)
    on_website = models.BooleanField("Usable on the website", default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_active", "code"]

    def __str__(self):
        return self.code

    def clean(self):
        self.code = (self.code or "").strip().upper().replace(" ", "")
        if bool(self.percent_off) == bool(self.amount_off):
            raise ValidationError("Set either a percentage or a KES amount off (not both).")
        if self.percent_off and self.percent_off > 100:
            raise ValidationError({"percent_off": "Can't be more than 100%."})
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValidationError({"valid_until": "Must be on or after the start date."})

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper().replace(" ", "")
        super().save(*args, **kwargs)

    @property
    def summary(self):
        return f"{self.percent_off:g}% off" if self.percent_off else f"KES {self.amount_off:,.0f} off"


class StayDiscount(models.Model):
    """Automatic long-stay discount, e.g. 7+ nights = 10% off."""

    min_nights = models.PositiveSmallIntegerField(validators=[MinValueValidator(2)])
    percent_off = models.DecimalField(max_digits=5, decimal_places=2,
                                      validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(Decimal("90"))])
    room_type = models.ForeignKey(RoomType, null=True, blank=True, on_delete=models.CASCADE,
                                  help_text="Leave empty for all room types.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["min_nights"]

    def __str__(self):
        return f"{self.min_nights}+ nights: {self.percent_off:g}% off"


class CorporateAccount(models.Model):
    """A company with a negotiated rate."""

    name = models.CharField(max_length=120, unique=True)
    percent_off = models.DecimalField("Negotiated discount %", max_digits=5, decimal_places=2, default=Decimal("0"),
                                      validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("90"))])
    contact_name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    kra_pin = models.CharField("KRA PIN", max_length=20, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
