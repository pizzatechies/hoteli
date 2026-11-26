import json
from decimal import Decimal
from unittest import mock

from django.test import override_settings
from django.urls import reverse

from bookings import services
from bookings.models import Booking, Payment
from hoteli.testutils import HotelTestCase
from notifications import sms
from notifications.models import SmsMessage


def at_response(status="Success", code=101):
    resp = mock.Mock(status_code=201)
    resp.json.return_value = {"SMSMessageData": {"Message": "Sent to 1/1", "Recipients": [
        {"statusCode": code, "number": "+254712345678", "status": status, "cost": "KES 0.8000",
         "messageId": "ATXid_123"}]}}
    resp.text = json.dumps(resp.json.return_value)
    return resp


class SmsTests(HotelTestCase):
    def test_numbers_are_normalised(self):
        self.assertEqual(sms.to_msisdn("0712 345 678"), "+254712345678")
        self.assertEqual(sms.to_msisdn("+44 7700 900123"), "+447700900123")
        self.assertIsNone(sms.to_msisdn("123"))

    def test_console_backend_logs(self):
        with self.captureOnCommitCallbacks(execute=True):
            message = sms.queue_sms("0712345678", "Hello")
        message.refresh_from_db()
        self.assertEqual(message.status, SmsMessage.Status.LOGGED)

    @override_settings(SMS_BACKEND="africastalking", SMS_USERNAME="myhotel", SMS_API_KEY="k", SMS_SENDER_ID="HOTELI")
    def test_africastalking_sends(self):
        with mock.patch("notifications.sms.requests.post", return_value=at_response()) as post:
            with self.captureOnCommitCallbacks(execute=True):
                message = sms.queue_sms("0712345678", "Hello")
        message.refresh_from_db()
        self.assertEqual(message.status, SmsMessage.Status.SENT)
        self.assertEqual(message.provider_id, "ATXid_123")
        self.assertEqual(post.call_args.args[0], "https://api.africastalking.com/version1/messaging")
        self.assertEqual(post.call_args.kwargs["data"]["from"], "HOTELI")
        self.assertEqual(post.call_args.kwargs["headers"]["apiKey"], "k")

    @override_settings(SMS_BACKEND="africastalking", SMS_USERNAME="sandbox", SMS_API_KEY="k")
    def test_failures_are_retried_then_marked_failed(self):
        with mock.patch("notifications.sms.requests.post", return_value=at_response("InvalidPhoneNumber", 403)):
            with self.captureOnCommitCallbacks(execute=True):
                message = sms.queue_sms("0712345678", "Hello")
            message.refresh_from_db()
            self.assertEqual(message.status, SmsMessage.Status.QUEUED)
            sms.retry_queued()
            sms.retry_queued()
        message.refresh_from_db()
        self.assertEqual(message.status, SmsMessage.Status.FAILED)
        self.assertEqual(message.attempts, 3)

    def test_guest_gets_confirmation_payment_and_welcome_sms(self):
        b = self.make_booking(ci=0, co=2, status=Booking.Status.PENDING, deposit_required=Decimal("1000"))
        with self.captureOnCommitCallbacks(execute=True):
            services.record_payment(booking=b, amount=Decimal("1000"), method=Payment.Method.CASH)
        kinds = set(SmsMessage.objects.values_list("kind", flat=True))
        self.assertEqual(kinds, {"PAYMENT_RECEIVED", "BOOKING_CONFIRMED"})
        receipt = SmsMessage.objects.get(kind="PAYMENT_RECEIVED")
        self.assertIn("KES 1,000", receipt.body)
        self.assertIn(b.reference, receipt.body)
        with self.captureOnCommitCallbacks(execute=True):
            services.check_in(b)
        self.assertIn("room 101", SmsMessage.objects.get(kind="CHECK_IN").body)

    def test_hotel_can_turn_off_automatic_sms(self):
        from core.models import HotelSettings

        hotel = HotelSettings.objects.get_or_create(pk=1)[0]
        hotel.sms_payment_receipt = False
        hotel.save()
        b = self.make_booking()
        with self.captureOnCommitCallbacks(execute=True):
            services.record_payment(booking=b, amount=Decimal("10"), method=Payment.Method.CASH)
        self.assertFalse(SmsMessage.objects.filter(kind="PAYMENT_RECEIVED").exists())

    def test_staff_send_from_booking(self):
        b = self.make_booking()
        self.login(self.reception)
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(reverse("notifications:send"), {"booking": b.pk, "phone": b.guest.phone,
                                                                    "body": "Your room is ready"})
        self.assertRedirects(resp, reverse("bookings:detail", args=[b.pk]))
        self.assertTrue(SmsMessage.objects.filter(booking=b, body="Your room is ready").exists())
        self.assertContains(self.client.get(reverse("notifications:list")), "Your room is ready")
        self.login(self.hk)
        self.assertEqual(self.client.get(reverse("notifications:list")).status_code, 403)
