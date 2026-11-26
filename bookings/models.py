import datetime
import secrets
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Case, DecimalField, F, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone

ZERO = Decimal("0.00")
MONEY = DecimalField(max_digits=14, decimal_places=2)
REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I to avoid typos on M-Pesa


def generate_booking_reference():
    while True:
        ref = "HB" + "".join(secrets.choice(REF_ALPHABET) for _ in range(6))
        if not Booking.objects.filter(reference=ref).exists():
            return ref


def signed_payment_sum():
    """Expression: payments minus refunds, ignoring voided rows (use inside Sum)."""
    return Case(
        When(kind="REFUND", then=-F("amount")),
        default=F("amount"),
        output_field=MONEY,
    )


class Guest(models.Model):
    class IDType(models.TextChoices):
        NATIONAL_ID = "NATIONAL_ID", "National ID"
        PASSPORT = "PASSPORT", "Passport"
        ALIEN_ID = "ALIEN_ID", "Alien ID"
        DRIVING_LICENSE = "DRIVING_LICENSE", "Driving licence"
        OTHER = "OTHER", "Other"

    class Gender(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"
        OTHER = "O", "Other"

    first_name = models.CharField(max_length=60)
    last_name = models.CharField(max_length=60)
    phone = models.CharField(max_length=20, help_text="e.g. 0712 345 678")
    email = models.EmailField(blank=True)
    id_type = models.CharField("ID type", max_length=20, choices=IDType.choices, default=IDType.NATIONAL_ID)
    id_number = models.CharField("ID / passport number", max_length=40, blank=True)
    nationality = models.CharField(max_length=60, default="Kenyan")
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True)
    address = models.CharField(max_length=255, blank=True)
    company = models.CharField(max_length=120, blank=True)
    vehicle_registration = models.CharField(max_length=20, blank=True)
    is_vip = models.BooleanField("VIP", default=False)
    is_blacklisted = models.BooleanField(default=False)
    blacklist_reason = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["first_name", "last_name"]
        indexes = [
            models.Index(fields=["phone"]),
            models.Index(fields=["id_number"]),
            models.Index(fields=["email"]),
        ]

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()


class BookingQuerySet(models.QuerySet):
    def active(self):
        return self.filter(status__in=Booking.ACTIVE_STATUSES)

    def overlapping(self, check_in, check_out):
        """Bookings whose stay overlaps [check_in, check_out). Back-to-back stays do not overlap."""
        return self.filter(check_in_date__lt=check_out, check_out_date__gt=check_in)

    def with_totals(self):
        charges = (
            Charge.objects.filter(booking=OuterRef("pk"), is_void=False)
            .values("booking")
            .annotate(total=Sum("amount"))
            .values("total")
        )
        payments = (
            Payment.objects.filter(booking=OuterRef("pk"), is_void=False)
            .values("booking")
            .annotate(total=Sum(signed_payment_sum()))
            .values("total")
        )
        return self.annotate(
            _charges_total=Coalesce(Subquery(charges, output_field=MONEY), Value(ZERO), output_field=MONEY),
            _payments_total=Coalesce(Subquery(payments, output_field=MONEY), Value(ZERO), output_field=MONEY),
        )


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        CHECKED_IN = "CHECKED_IN", "Checked in"
        CHECKED_OUT = "CHECKED_OUT", "Checked out"
        CANCELLED = "CANCELLED", "Cancelled"
        NO_SHOW = "NO_SHOW", "No show"

    class Source(models.TextChoices):
        WALK_IN = "WALK_IN", "Walk-in"
        PHONE = "PHONE", "Phone"
        EMAIL = "EMAIL", "Email"
        WEBSITE = "WEBSITE", "Website"
        OTA = "OTA", "Online travel agent"
        AGENT = "AGENT", "Travel agent"
        CORPORATE = "CORPORATE", "Corporate"

    ACTIVE_STATUSES = (Status.PENDING, Status.CONFIRMED, Status.CHECKED_IN)

    reference = models.CharField(max_length=12, unique=True, editable=False)
    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    guest = models.ForeignKey(Guest, on_delete=models.PROTECT, related_name="bookings")
    room = models.ForeignKey("rooms.Room", on_delete=models.PROTECT, related_name="bookings")
    check_in_date = models.DateField()
    check_out_date = models.DateField()
    adults = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    children = models.PositiveSmallIntegerField(default=0)
    rate = models.DecimalField(
        "Rate per night", max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    deposit_required = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    base_rate = models.DecimalField("Rate before discount", max_digits=10, decimal_places=2, null=True, blank=True)
    discount_label = models.CharField(max_length=100, blank=True)
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    promo_code = models.ForeignKey("rooms.PromoCode", null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="bookings")
    corporate_account = models.ForeignKey("rooms.CorporateAccount", null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="bookings")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.CONFIRMED, db_index=True)
    source = models.CharField(max_length=12, choices=Source.choices, default=Source.WALK_IN)
    special_requests = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)
    expires_at = models.DateTimeField(
        null=True, blank=True, help_text="Pending bookings are released automatically after this time."
    )
    actual_check_in = models.DateTimeField(null=True, blank=True)
    actual_check_out = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=255, blank=True)
    confirmation_sent = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="bookings_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BookingQuerySet.as_manager()

    class Meta:
        ordering = ["-check_in_date", "-created_at"]
        indexes = [models.Index(fields=["room", "check_in_date", "check_out_date"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(check_out_date__gt=F("check_in_date")), name="booking_checkout_after_checkin"
            )
        ]

    def __str__(self):
        return f"{self.reference} – {self.guest}"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = generate_booking_reference()
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------ dates
    @property
    def nights(self):
        return max((self.check_out_date - self.check_in_date).days, 0)

    def stay_dates(self):
        return [self.check_in_date + datetime.timedelta(days=i) for i in range(self.nights)]

    @property
    def is_active(self):
        return self.status in self.ACTIVE_STATUSES

    @property
    def is_overdue_departure(self):
        return self.status == self.Status.CHECKED_IN and self.check_out_date < timezone.localdate()

    @property
    def is_expired_hold(self):
        return (
            self.status == self.Status.PENDING
            and self.expires_at is not None
            and self.expires_at <= timezone.now()
        )

    # ------------------------------------------------------------------ money
    @property
    def charges_total(self):
        if hasattr(self, "_charges_total"):
            return self._charges_total
        return self.charges.filter(is_void=False).aggregate(t=Sum("amount"))["t"] or ZERO

    @property
    def payments_total(self):
        if hasattr(self, "_payments_total"):
            return self._payments_total
        return (
            self.payments.filter(is_void=False).aggregate(t=Sum(signed_payment_sum()))["t"] or ZERO
        )

    @property
    def balance(self):
        """Posted charges minus payments (what the guest owes right now)."""
        return self.charges_total - self.payments_total

    def projected_room_total(self):
        room_charges = self.charges.filter(is_void=False, category=Charge.Category.ROOM)
        posted_total = room_charges.aggregate(t=Sum("amount"))["t"] or ZERO
        if self.status not in self.ACTIVE_STATUSES:
            return posted_total
        posted_nights = set(room_charges.values_list("service_date", flat=True))
        remaining = [d for d in self.stay_dates() if d not in posted_nights]
        if not remaining and not posted_nights:
            remaining = [self.check_in_date]  # minimum one night
        return posted_total + self.rate * len(remaining)

    def projected_total(self):
        other = (
            self.charges.filter(is_void=False).exclude(category=Charge.Category.ROOM).aggregate(t=Sum("amount"))["t"]
            or ZERO
        )
        return self.projected_room_total() + other

    def projected_balance(self):
        return self.projected_total() - self.payments_total

    @property
    def amount_due(self):
        return max(self.projected_balance(), ZERO)

    @property
    def deposit_outstanding(self):
        return max(self.deposit_required - self.payments_total, ZERO)

    # ------------------------------------------------------------------ workflow flags
    @property
    def can_check_in(self):
        return self.status in (self.Status.PENDING, self.Status.CONFIRMED) and self.check_in_date <= timezone.localdate()

    @property
    def can_check_out(self):
        return self.status == self.Status.CHECKED_IN

    @property
    def can_cancel(self):
        return self.status in (self.Status.PENDING, self.Status.CONFIRMED)

    @property
    def can_edit(self):
        return self.status in self.ACTIVE_STATUSES

    @property
    def accepts_payments(self):
        return self.status not in (self.Status.CANCELLED, self.Status.NO_SHOW) or self.balance > 0


class Charge(models.Model):
    class Category(models.TextChoices):
        ROOM = "ROOM", "Room"
        FOOD = "FOOD", "Food"
        BEVERAGE = "BEVERAGE", "Beverage"
        LAUNDRY = "LAUNDRY", "Laundry"
        MINIBAR = "MINIBAR", "Minibar"
        SPA = "SPA", "Spa & wellness"
        TRANSPORT = "TRANSPORT", "Transport"
        CONFERENCE = "CONFERENCE", "Conference & events"
        LATE_CHECKOUT = "LATE_CHECKOUT", "Late checkout"
        DAMAGE = "DAMAGE", "Damages"
        CANCELLATION = "CANCELLATION", "Cancellation fee"
        OTHER = "OTHER", "Other"
        DISCOUNT = "DISCOUNT", "Discount / adjustment"

    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name="charges")
    category = models.CharField(max_length=15, choices=Category.choices, default=Category.OTHER)
    description = models.CharField(max_length=200)
    service_date = models.DateField(default=timezone.localdate)
    quantity = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("1"),
                                   validators=[MinValueValidator(Decimal("0.01"))])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    amount = models.DecimalField(max_digits=12, decimal_places=2, editable=False)
    pos_order = models.ForeignKey(
        "pos.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="folio_charges"
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    is_void = models.BooleanField(default=False)
    void_reason = models.CharField(max_length=200, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["service_date", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["booking", "service_date"],
                condition=Q(category="ROOM", is_void=False),
                name="unique_room_charge_per_night",
            )
        ]

    def __str__(self):
        return f"{self.description} ({self.amount})"

    def save(self, *args, **kwargs):
        amount = (self.quantity * self.unit_price).quantize(Decimal("0.01"))
        self.amount = -amount if self.category == self.Category.DISCOUNT else amount
        super().save(*args, **kwargs)


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        MPESA = "MPESA", "M-Pesa"
        CARD = "CARD", "Card"
        BANK = "BANK", "Bank transfer"
        CHEQUE = "CHEQUE", "Cheque"
        OTHER = "OTHER", "Other"

    class Kind(models.TextChoices):
        PAYMENT = "PAYMENT", "Payment"
        REFUND = "REFUND", "Refund"

    receipt_number = models.CharField(max_length=20, unique=True, null=True, editable=False)
    booking = models.ForeignKey(
        Booking, null=True, blank=True, on_delete=models.PROTECT, related_name="payments"
    )
    order = models.ForeignKey(
        "pos.Order", null=True, blank=True, on_delete=models.PROTECT, related_name="payments"
    )
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.PAYMENT)
    method = models.CharField(max_length=8, choices=Method.choices, default=Method.CASH)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    reference = models.CharField(max_length=60, blank=True, help_text="M-Pesa code, card slip or bank ref")
    payer_phone = models.CharField(max_length=20, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    is_void = models.BooleanField(default=False)
    void_reason = models.CharField(max_length=200, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(booking__isnull=False) | Q(order__isnull=False), name="payment_has_target"
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive"),
        ]

    def __str__(self):
        return f"{self.receipt_number or 'Payment'} {self.get_method_display()} {self.amount}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.receipt_number:
            self.receipt_number = f"RCT-{self.pk:06d}"
            Payment.objects.filter(pk=self.pk).update(receipt_number=self.receipt_number)

    @property
    def signed_amount(self):
        return -self.amount if self.kind == self.Kind.REFUND else self.amount

    @property
    def target_label(self):
        if self.booking_id:
            return self.booking.reference
        if self.order_id:
            return self.order.number
        return ""


class NightAuditRun(models.Model):
    business_date = models.DateField(unique=True)
    run_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    room_charges_posted = models.PositiveIntegerField(default=0)
    no_shows = models.PositiveIntegerField(default=0)
    expired_holds = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-business_date"]

    def __str__(self):
        return f"Night audit {self.business_date}"
