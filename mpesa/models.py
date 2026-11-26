import uuid

from django.conf import settings
from django.db import models


class MpesaTransaction(models.Model):
    """A Lipa Na M-Pesa Online (STK push) request and its outcome."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Awaiting customer"
        SUCCESS = "SUCCESS", "Paid"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled by customer"
        TIMEOUT = "TIMEOUT", "Timed out"

    class Source(models.TextChoices):
        STAFF = "STAFF", "Staff"
        WEBSITE = "WEBSITE", "Website"

    FINAL_STATUSES = (Status.SUCCESS, Status.FAILED, Status.CANCELLED)

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    booking = models.ForeignKey(
        "bookings.Booking", null=True, blank=True, on_delete=models.PROTECT, related_name="mpesa_transactions"
    )
    order = models.ForeignKey(
        "pos.Order", null=True, blank=True, on_delete=models.PROTECT, related_name="mpesa_transactions"
    )
    phone = models.CharField(max_length=15)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    account_reference = models.CharField(max_length=12)
    description = models.CharField(max_length=13)
    merchant_request_id = models.CharField(max_length=80, blank=True)
    checkout_request_id = models.CharField(max_length=80, unique=True, null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    result_code = models.CharField(max_length=20, blank=True)
    result_desc = models.CharField(max_length=255, blank=True)
    mpesa_receipt = models.CharField(max_length=30, blank=True, db_index=True)
    transaction_date = models.DateTimeField(null=True, blank=True)
    paid_phone = models.CharField(max_length=20, blank=True)
    is_simulated = models.BooleanField(default=False)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.STAFF)
    raw_response = models.JSONField(null=True, blank=True)
    raw_callback = models.JSONField(null=True, blank=True)
    last_queried_at = models.DateTimeField(null=True, blank=True)
    query_attempts = models.PositiveSmallIntegerField(default=0)
    payment = models.OneToOneField(
        "bookings.Payment", null=True, blank=True, on_delete=models.SET_NULL, related_name="mpesa_transaction"
    )
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "M-Pesa STK transaction"

    def __str__(self):
        return f"STK {self.phone} KES {self.amount} [{self.status}]"

    @property
    def is_final(self):
        return self.status in self.FINAL_STATUSES

    @property
    def target_label(self):
        if self.booking_id:
            return self.booking.reference
        if self.order_id:
            return self.order.number
        return self.account_reference

    @property
    def masked_phone(self):
        p = self.phone
        return f"{p[:5]}***{p[-3:]}" if len(p) >= 9 else p


class C2BTransaction(models.Model):
    """A payment made directly to the Paybill (customer enters the booking reference as account number)."""

    class Status(models.TextChoices):
        MATCHED = "MATCHED", "Auto-matched"
        UNMATCHED = "UNMATCHED", "Unmatched"
        ALLOCATED = "ALLOCATED", "Manually allocated"
        IGNORED = "IGNORED", "Ignored"

    trans_id = models.CharField("M-Pesa code", max_length=30, unique=True)
    trans_type = models.CharField(max_length=40, blank=True)
    trans_time = models.DateTimeField(null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    business_short_code = models.CharField(max_length=20, blank=True)
    bill_ref_number = models.CharField("Account number", max_length=60, blank=True)
    msisdn = models.CharField(max_length=80, blank=True)
    first_name = models.CharField(max_length=60, blank=True)
    middle_name = models.CharField(max_length=60, blank=True)
    last_name = models.CharField(max_length=60, blank=True)
    org_account_balance = models.CharField(max_length=40, blank=True)
    raw = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.UNMATCHED, db_index=True)
    booking = models.ForeignKey(
        "bookings.Booking", null=True, blank=True, on_delete=models.PROTECT, related_name="c2b_transactions"
    )
    order = models.ForeignKey(
        "pos.Order", null=True, blank=True, on_delete=models.PROTECT, related_name="c2b_transactions"
    )
    payment = models.OneToOneField(
        "bookings.Payment", null=True, blank=True, on_delete=models.SET_NULL, related_name="c2b_transaction"
    )
    allocated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    allocated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "M-Pesa paybill (C2B) transaction"

    def __str__(self):
        return f"{self.trans_id} KES {self.amount} ({self.bill_ref_number})"

    @property
    def payer_name(self):
        return " ".join(p for p in [self.first_name, self.middle_name, self.last_name] if p)


class MpesaCallbackLog(models.Model):
    """Every raw callback Safaricom sends us, kept for troubleshooting and reconciliation."""

    class Kind(models.TextChoices):
        STK = "STK", "STK push result"
        C2B_VALIDATION = "C2B_VALIDATION", "C2B validation"
        C2B_CONFIRMATION = "C2B_CONFIRMATION", "C2B confirmation"
        B2C_RESULT = "B2C_RESULT", "Refund (B2C) result"
        B2C_TIMEOUT = "B2C_TIMEOUT", "Refund (B2C) timeout"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    payload = models.JSONField(null=True, blank=True)
    remote_addr = models.CharField(max_length=60, blank=True)
    processed = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True)
    error = models.TextField(blank=True)
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.get_kind_display()} @ {self.received_at:%Y-%m-%d %H:%M:%S}"


class B2CRefund(models.Model):
    """A refund sent from the business to a guest's M-Pesa (Daraja B2C)."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Sending"
        SUCCESS = "SUCCESS", "Refunded"
        FAILED = "FAILED", "Failed"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    booking = models.ForeignKey("bookings.Booking", on_delete=models.PROTECT, related_name="mpesa_refunds")
    phone = models.CharField(max_length=15)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=100)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING, db_index=True)
    originator_conversation_id = models.CharField(max_length=60, unique=True)
    conversation_id = models.CharField(max_length=80, blank=True, db_index=True)
    transaction_id = models.CharField("M-Pesa code", max_length=30, blank=True)
    receiver_name = models.CharField(max_length=120, blank=True)
    result_code = models.CharField(max_length=20, blank=True)
    result_desc = models.CharField(max_length=255, blank=True)
    is_simulated = models.BooleanField(default=False)
    raw_response = models.JSONField(null=True, blank=True)
    raw_result = models.JSONField(null=True, blank=True)
    payment = models.OneToOneField("bookings.Payment", null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="mpesa_refund")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "M-Pesa refund (B2C)"

    def __str__(self):
        return f"Refund KES {self.amount} to {self.phone} [{self.status}]"
