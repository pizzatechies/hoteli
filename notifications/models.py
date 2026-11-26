from django.conf import settings
from django.db import models


class SmsMessage(models.Model):
    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        SENT = "SENT", "Sent"
        LOGGED = "LOGGED", "Logged (test mode)"
        FAILED = "FAILED", "Failed"

    class Kind(models.TextChoices):
        BOOKING_CONFIRMED = "BOOKING_CONFIRMED", "Booking confirmed"
        PAYMENT_RECEIVED = "PAYMENT_RECEIVED", "Payment received"
        CHECK_IN = "CHECK_IN", "Check-in welcome"
        FEEDBACK = "FEEDBACK", "Feedback request"
        CUSTOM = "CUSTOM", "Custom message"

    to = models.CharField(max_length=20)
    body = models.TextField()
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.CUSTOM)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.QUEUED, db_index=True)
    booking = models.ForeignKey("bookings.Booking", null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="sms_messages")
    provider_id = models.CharField(max_length=80, blank=True)
    cost = models.CharField(max_length=30, blank=True)
    error = models.CharField(max_length=255, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "SMS message"

    def __str__(self):
        return f"SMS to {self.to} ({self.get_status_display()})"

    @property
    def segments(self):
        return max(1, -(-len(self.body) // 153)) if len(self.body) > 160 else 1
