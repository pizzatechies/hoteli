import base64
import datetime
import json
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from bookings.models import Booking, Payment
from bookings.services import record_payment
from hoteli.testutils import HotelTestCase
from mpesa import services
from mpesa.models import C2BTransaction, MpesaCallbackLog, MpesaTransaction
from mpesa.utils import normalize_phone, parse_mpesa_timestamp, stk_amount

LIVE = dict(
    MPESA_SIMULATE=False, MPESA_CONSUMER_KEY="key", MPESA_CONSUMER_SECRET="secret", MPESA_ENVIRONMENT="sandbox",
    MPESA_SHORTCODE="174379", MPESA_PASSKEY="passkey", MPESA_CALLBACK_BASE_URL="https://hotel.example.com",
    MPESA_CALLBACK_TOKEN="tok123", MPESA_TRANSACTION_TYPE="CustomerPayBillOnline", MPESA_TILL_NUMBER="",
)


def fake_response(status=200, payload=None):
    resp = mock.Mock()
    resp.status_code = status
    resp.json.return_value = payload or {}
    resp.text = json.dumps(payload or {})
    return resp


TOKEN = fake_response(200, {"access_token": "abc", "expires_in": "3599"})
STK_OK = fake_response(200, {
    "MerchantRequestID": "29115-34620561-1", "CheckoutRequestID": "ws_CO_191220191020363925",
    "ResponseCode": "0", "ResponseDescription": "Success. Request accepted for processing",
    "CustomerMessage": "Success. Request accepted for processing",
})


def stk_callback(checkout_id="ws_CO_191220191020363925", code=0, amount=5000, receipt="NLJ7RT61SV"):
    body = {"MerchantRequestID": "29115-34620561-1", "CheckoutRequestID": checkout_id, "ResultCode": code,
            "ResultDesc": "The service request is processed successfully."}
    if code == 0:
        body["CallbackMetadata"] = {"Item": [
            {"Name": "Amount", "Value": amount}, {"Name": "MpesaReceiptNumber", "Value": receipt},
            {"Name": "Balance"}, {"Name": "TransactionDate", "Value": 20261125102115},
            {"Name": "PhoneNumber", "Value": 254712345678},
        ]}
    return {"Body": {"stkCallback": body}}


class UtilsTests(SimpleTestCase):
    def test_normalize_phone(self):
        for raw in ["0712345678", "712345678", "+254712345678", "254 712 345 678", "0712-345-678"]:
            self.assertEqual(normalize_phone(raw), "254712345678")
        self.assertEqual(normalize_phone("0110123456"), "254110123456")
        for bad in ["", "12345", "0812345678", "+447700900123", "07123456789"]:
            with self.assertRaises(ValueError):
                normalize_phone(bad)

    def test_stk_amount_rounds_up_and_limits(self):
        self.assertEqual(stk_amount("99.01"), Decimal("100"))
        self.assertEqual(stk_amount(Decimal("100.00")), Decimal("100"))
        self.assertEqual(stk_amount("0.4"), Decimal("1"))
        with self.assertRaises(ValueError):
            stk_amount("0")
        with self.assertRaises(ValueError):
            stk_amount("250001")

    def test_parse_timestamp(self):
        dt = parse_mpesa_timestamp(20261125102115)
        self.assertEqual((dt.year, dt.hour, dt.second), (2026, 10, 15))
        self.assertIsNone(parse_mpesa_timestamp(None))
        self.assertIsNone(parse_mpesa_timestamp("garbage"))


@override_settings(**LIVE)
class StkPushTests(HotelTestCase):
    def setUp(self):
        super().setUp()
        self.booking = self.make_booking(ci=1, co=2)

    @mock.patch("mpesa.daraja.requests.post", return_value=STK_OK)
    @mock.patch("mpesa.daraja.requests.get", return_value=TOKEN)
    def test_push_sends_correct_payload(self, get, post):
        tx = services.initiate_stk_push(phone="0712 345 678", amount=Decimal("4999.50"), booking=self.booking)
        self.assertEqual(tx.status, MpesaTransaction.Status.PENDING)
        self.assertEqual(tx.checkout_request_id, "ws_CO_191220191020363925")
        self.assertEqual(tx.amount, Decimal("5000"))
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["Amount"], 5000)
        self.assertEqual(payload["PartyA"], "254712345678")
        self.assertEqual(payload["PartyB"], "174379")
        self.assertEqual(payload["AccountReference"], self.booking.reference)
        self.assertLessEqual(len(payload["TransactionDesc"]), 13)
        self.assertEqual(payload["CallBackURL"], "https://hotel.example.com/payments/callbacks/stk/tok123/")
        decoded = base64.b64decode(payload["Password"]).decode()
        self.assertEqual(decoded, "174379passkey" + payload["Timestamp"])
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer abc")

    @mock.patch("mpesa.daraja.requests.post", return_value=STK_OK)
    @mock.patch("mpesa.daraja.requests.get", return_value=TOKEN)
    def test_token_is_cached(self, get, post):
        services.initiate_stk_push(phone="0712345678", amount=10, booking=self.booking)
        other = self.make_booking(room=self.r102, ci=1, co=2)
        post.return_value = fake_response(200, {**STK_OK.json.return_value, "CheckoutRequestID": "ws_CO_2"})
        services.initiate_stk_push(phone="0712345678", amount=10, booking=other)
        self.assertEqual(get.call_count, 1)

    @mock.patch("mpesa.daraja.requests.get", return_value=TOKEN)
    def test_expired_token_is_refreshed_once(self, get):
        with mock.patch("mpesa.daraja.requests.post", side_effect=[fake_response(401, {}), STK_OK]) as post:
            tx = services.initiate_stk_push(phone="0712345678", amount=10, booking=self.booking)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(tx.status, MpesaTransaction.Status.PENDING)

    @mock.patch("mpesa.daraja.requests.get", return_value=TOKEN)
    def test_daraja_error_marks_failed(self, get):
        error = fake_response(400, {"requestId": "1", "errorCode": "400.002.02", "errorMessage": "Bad Request - Invalid PhoneNumber"})
        with mock.patch("mpesa.daraja.requests.post", return_value=error):
            with self.assertRaisesMessage(services.MpesaError, "Invalid PhoneNumber"):
                services.initiate_stk_push(phone="0712345678", amount=10, booking=self.booking)
        tx = MpesaTransaction.objects.get()
        self.assertEqual(tx.status, MpesaTransaction.Status.FAILED)

    def test_bad_auth_gives_helpful_error(self):
        with mock.patch("mpesa.daraja.requests.get", return_value=fake_response(400, {})):
            with self.assertRaisesMessage(services.MpesaError, "authentication failed"):
                services.initiate_stk_push(phone="0712345678", amount=10, booking=self.booking)

    def test_invalid_phone_rejected_before_calling_daraja(self):
        with mock.patch("mpesa.daraja.requests.post") as post:
            with self.assertRaises(services.MpesaError):
                services.initiate_stk_push(phone="12345", amount=10, booking=self.booking)
        post.assert_not_called()

    @mock.patch("mpesa.daraja.requests.post", return_value=STK_OK)
    @mock.patch("mpesa.daraja.requests.get", return_value=TOKEN)
    def test_resend_cooldown(self, get, post):
        services.initiate_stk_push(phone="0712345678", amount=10, booking=self.booking)
        with self.assertRaisesMessage(services.MpesaError, "30 seconds"):
            services.initiate_stk_push(phone="0712345678", amount=10, booking=self.booking)


@override_settings(**LIVE)
class CallbackTests(HotelTestCase):
    def setUp(self):
        super().setUp()
        self.booking = self.make_booking(ci=1, co=2, status=Booking.Status.PENDING, deposit_required=Decimal("2500"),
                                         expires_at=timezone.now() + datetime.timedelta(minutes=30))
        self.tx = MpesaTransaction.objects.create(
            booking=self.booking, phone="254712345678", amount=Decimal("5000"),
            account_reference=self.booking.reference, description="Room booking",
            checkout_request_id="ws_CO_191220191020363925", merchant_request_id="29115-34620561-1",
        )
        self.url = reverse("mpesa:stk_callback", args=["tok123"])

    def post(self, payload, url=None):
        return self.client.post(url or self.url, data=json.dumps(payload), content_type="application/json")

    def test_success_callback_records_payment_and_confirms_booking(self):
        resp = self.post(stk_callback())
        self.assertEqual(resp.json(), {"ResultCode": 0, "ResultDesc": "Accepted"})
        self.tx.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(self.tx.status, MpesaTransaction.Status.SUCCESS)
        self.assertEqual(self.tx.mpesa_receipt, "NLJ7RT61SV")
        self.assertEqual(self.tx.payment.reference, "NLJ7RT61SV")
        self.assertEqual(self.booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(self.booking.payments_total, Decimal("5000"))
        self.assertTrue(MpesaCallbackLog.objects.get().processed)

    def test_duplicate_callback_is_idempotent(self):
        self.post(stk_callback())
        self.post(stk_callback())
        self.assertEqual(Payment.objects.count(), 1)

    def test_cancelled_callback(self):
        self.post(stk_callback(code=1032))
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, MpesaTransaction.Status.CANCELLED)
        self.assertIn("cancelled", self.tx.result_desc)
        self.assertEqual(Payment.objects.count(), 0)

    def test_insufficient_funds_callback(self):
        self.post(stk_callback(code=1))
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, MpesaTransaction.Status.FAILED)
        self.assertIn("insufficient", self.tx.result_desc)

    def test_failure_never_downgrades_success(self):
        self.post(stk_callback())
        self.post(stk_callback(code=1032))
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, MpesaTransaction.Status.SUCCESS)

    def test_wrong_token_is_rejected(self):
        resp = self.post(stk_callback(), url=reverse("mpesa:stk_callback", args=["wrong"]))
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(Payment.objects.count(), 0)

    def test_invalid_json_logged(self):
        resp = self.client.post(self.url, data="not json", content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(MpesaCallbackLog.objects.get().error, "Invalid JSON body")

    def test_unknown_checkout_id_acknowledged(self):
        resp = self.post(stk_callback(checkout_id="ws_CO_unknown"))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(MpesaCallbackLog.objects.get().processed)

    def test_receipt_already_keyed_by_staff_is_linked_not_duplicated(self):
        record_payment(booking=self.booking, amount=Decimal("5000"), method=Payment.Method.MPESA, reference="NLJ7RT61SV")
        self.post(stk_callback())
        self.assertEqual(Payment.objects.count(), 1)
        self.tx.refresh_from_db()
        self.assertIsNotNone(self.tx.payment_id)

    def test_query_fallback_when_callback_is_lost(self):
        MpesaTransaction.objects.filter(pk=self.tx.pk).update(created_at=timezone.now() - datetime.timedelta(seconds=60))
        self.tx.refresh_from_db()
        query_ok = fake_response(200, {"ResponseCode": "0", "ResultCode": "0",
                                       "ResultDesc": "The service request is processed successfully."})
        with mock.patch("mpesa.daraja.requests.get", return_value=TOKEN), \
                mock.patch("mpesa.daraja.requests.post", return_value=query_ok):
            data = self.client.get(reverse("mpesa:status", args=[self.tx.uuid])).json()
        self.assertTrue(data["success"])
        payment = Payment.objects.get()
        self.assertTrue(payment.reference.startswith("STK-"))
        # The real callback arrives later with the receipt number.
        self.post(stk_callback())
        payment.refresh_from_db()
        self.assertEqual(payment.reference, "NLJ7RT61SV")
        self.assertEqual(Payment.objects.count(), 1)

    def test_still_processing_then_timeout_then_late_success(self):
        processing = fake_response(500, {"requestId": "x", "errorCode": "500.001.1001",
                                         "errorMessage": "The transaction is being processed"})
        MpesaTransaction.objects.filter(pk=self.tx.pk).update(created_at=timezone.now() - datetime.timedelta(seconds=60))
        with mock.patch("mpesa.daraja.requests.get", return_value=TOKEN), \
                mock.patch("mpesa.daraja.requests.post", return_value=processing):
            tx = services.refresh_transaction_status(MpesaTransaction.objects.get(pk=self.tx.pk))
            self.assertEqual(tx.status, MpesaTransaction.Status.PENDING)
            MpesaTransaction.objects.filter(pk=self.tx.pk).update(
                created_at=timezone.now() - datetime.timedelta(seconds=400), last_queried_at=None)
            tx = services.refresh_transaction_status(MpesaTransaction.objects.get(pk=self.tx.pk))
            self.assertEqual(tx.status, MpesaTransaction.Status.TIMEOUT)
        self.post(stk_callback())
        tx.refresh_from_db()
        self.assertEqual(tx.status, MpesaTransaction.Status.SUCCESS)
        self.assertEqual(Payment.objects.count(), 1)

    def test_query_reports_cancellation(self):
        MpesaTransaction.objects.filter(pk=self.tx.pk).update(created_at=timezone.now() - datetime.timedelta(seconds=60))
        cancelled = fake_response(200, {"ResponseCode": "0", "ResultCode": "1032", "ResultDesc": "Request cancelled by user"})
        with mock.patch("mpesa.daraja.requests.get", return_value=TOKEN), \
                mock.patch("mpesa.daraja.requests.post", return_value=cancelled):
            tx = services.refresh_transaction_status(MpesaTransaction.objects.get(pk=self.tx.pk))
        self.assertEqual(tx.status, MpesaTransaction.Status.CANCELLED)


@override_settings(**LIVE)
class C2BTests(HotelTestCase):
    def setUp(self):
        super().setUp()
        self.booking = self.make_booking(ci=1, co=2)
        self.url = reverse("mpesa:c2b_confirmation", args=["tok123"])

    def confirm(self, trans_id="RKTQDM7W6S", ref=None, amount="2500.00"):
        payload = {
            "TransactionType": "Pay Bill", "TransID": trans_id, "TransTime": "20261125063845",
            "TransAmount": amount, "BusinessShortCode": "600638", "BillRefNumber": ref or self.booking.reference,
            "MSISDN": "2547 ***** 126", "FirstName": "JANE",
        }
        return self.client.post(self.url, data=json.dumps(payload), content_type="application/json")

    def test_auto_match_by_booking_reference(self):
        resp = self.confirm(ref=self.booking.reference.lower())
        self.assertEqual(resp.json()["ResultCode"], 0)
        c2b = C2BTransaction.objects.get()
        self.assertEqual(c2b.status, C2BTransaction.Status.MATCHED)
        self.assertEqual(self.booking.payments_total, Decimal("2500"))

    def test_duplicate_confirmation_ignored(self):
        self.confirm()
        self.confirm()
        self.assertEqual(Payment.objects.count(), 1)

    def test_unmatched_then_manual_allocation(self):
        self.confirm(ref="room 101 jane")
        c2b = C2BTransaction.objects.get()
        self.assertEqual(c2b.status, C2BTransaction.Status.UNMATCHED)
        self.login(self.reception)
        self.client.post(reverse("mpesa:c2b_allocate", args=[c2b.pk]), {"reference": self.booking.reference})
        c2b.refresh_from_db()
        self.assertEqual(c2b.status, C2BTransaction.Status.ALLOCATED)
        self.assertEqual(self.booking.payments_total, Decimal("2500"))

    def test_staff_keying_code_uses_paybill_entry(self):
        self.confirm(ref="wrong")
        payment = services.record_manual_mpesa_payment(booking=self.booking, code="rktqdm7w6s", amount=Decimal("1"))
        self.assertEqual(payment.amount, Decimal("2500"))  # amount comes from M-Pesa, not the keyed value
        self.assertEqual(C2BTransaction.objects.get().payment, payment)

    def test_voiding_allocated_payment_returns_it_to_queue(self):
        from bookings.services import void_payment

        self.confirm()
        c2b = C2BTransaction.objects.get()
        void_payment(c2b.payment, reason="Wrong booking")
        c2b.refresh_from_db()
        self.assertEqual(c2b.status, C2BTransaction.Status.UNMATCHED)
        self.assertIsNone(c2b.payment)

    def test_validation_endpoint_accepts(self):
        resp = self.client.post(reverse("mpesa:c2b_validation", args=["tok123"]), data="{}",
                                content_type="application/json")
        self.assertEqual(resp.json()["ResultCode"], 0)


@override_settings(MPESA_SIMULATE=True)
class SimulationTests(HotelTestCase):
    def test_staff_prompt_and_simulated_success(self):
        b = self.make_booking(ci=0, co=1)
        self.login(self.reception)
        resp = self.client.post(reverse("mpesa:stk_start"), {"booking": b.pk, "phone": "0712345678", "amount": "5000"})
        tx = MpesaTransaction.objects.get()
        self.assertTrue(tx.is_simulated)
        self.assertRedirects(resp, reverse("bookings:detail", args=[b.pk]) + f"?tx={tx.uuid}")
        self.assertFalse(self.client.get(reverse("mpesa:status", args=[tx.uuid])).json()["final"])
        data = self.client.post(reverse("mpesa:simulate", args=[tx.uuid]), {"outcome": "success"}).json()
        self.assertTrue(data["success"])
        self.assertTrue(data["receipt"].startswith("S"))
        self.assertEqual(b.payments_total, Decimal("5000"))

    def test_simulated_wrong_pin(self):
        b = self.make_booking(ci=0, co=1)
        tx = services.initiate_stk_push(phone="0712345678", amount=100, booking=b)
        services.simulate_result(tx, "wrong_pin")
        tx.refresh_from_db()
        self.assertEqual(tx.status, MpesaTransaction.Status.FAILED)
        self.assertIn("PIN", tx.result_desc)

    @override_settings(MPESA_SIMULATE=False)
    def test_simulate_endpoint_disabled_when_live(self):
        b = self.make_booking(ci=0, co=1)
        tx = MpesaTransaction.objects.create(booking=b, phone="254712345678", amount=1, account_reference="x",
                                             description="x", is_simulated=True, checkout_request_id="ws_CO_SIM_1")
        resp = self.client.post(reverse("mpesa:simulate", args=[tx.uuid]), {"outcome": "success"})
        self.assertEqual(resp.status_code, 404)


B2C_LIVE = dict(LIVE, MPESA_B2C_INITIATOR_NAME="testapi", MPESA_B2C_SECURITY_CREDENTIAL="cred==",
                MPESA_B2C_SHORTCODE="600996", MPESA_B2C_COMMAND_ID="BusinessPayment")


def b2c_result(originator, code=0, receipt="NLJ41HAY6Q", amount=2000):
    result = {"ResultType": 0, "ResultCode": code, "ResultDesc": "The service request is processed successfully.",
              "OriginatorConversationID": originator, "ConversationID": "AG_20261126_123", "TransactionID": receipt}
    if code == 0:
        result["ResultParameters"] = {"ResultParameter": [
            {"Key": "TransactionAmount", "Value": amount}, {"Key": "TransactionReceipt", "Value": receipt},
            {"Key": "ReceiverPartyPublicName", "Value": "254712345678 - JANE DOE"}]}
    else:
        result["ResultDesc"] = "The initiator information is invalid."
    return {"Result": result}


class RefundTests(HotelTestCase):
    def setUp(self):
        super().setUp()
        self.booking = self.make_booking(ci=-2, co=0, status=Booking.Status.CHECKED_OUT)
        record_payment(booking=self.booking, amount=Decimal("5000"), method=Payment.Method.MPESA, reference="QAZ123WSX")

    @override_settings(MPESA_SIMULATE=True)
    def test_simulated_refund_is_recorded_on_folio(self):
        refund = services.initiate_refund(booking=self.booking, phone="0712345678", amount=2000, reason="Overpaid")
        self.assertEqual(refund.status, refund.Status.SUCCESS)
        self.assertEqual(refund.payment.kind, Payment.Kind.REFUND)
        self.assertEqual(self.booking.payments_total, Decimal("3000"))

    @override_settings(MPESA_SIMULATE=True)
    def test_cannot_refund_more_than_paid_including_pending(self):
        from mpesa.models import B2CRefund

        B2CRefund.objects.create(booking=self.booking, phone="254712345678", amount=4000, reason="x",
                                 originator_conversation_id="pending-1")
        with self.assertRaisesMessage(services.MpesaError, "at most KES 1,000"):
            services.initiate_refund(booking=self.booking, phone="0712345678", amount=2000, reason="Overpaid")

    @override_settings(**B2C_LIVE)
    def test_live_refund_payload_and_result_callback(self):
        ok = fake_response(200, {"ConversationID": "AG_20261126_123", "OriginatorConversationID": "x",
                                 "ResponseCode": "0", "ResponseDescription": "Accept the service request successfully."})
        with mock.patch("mpesa.daraja.requests.get", return_value=TOKEN), \
                mock.patch("mpesa.daraja.requests.post", return_value=ok) as post:
            refund = services.initiate_refund(booking=self.booking, phone="0712345678", amount=2000, reason="Overpaid")
        payload = post.call_args.kwargs["json"]
        self.assertTrue(post.call_args.args[0].endswith("/mpesa/b2c/v3/paymentrequest"))
        self.assertEqual(payload["PartyA"], "600996")
        self.assertEqual(payload["PartyB"], "254712345678")
        self.assertEqual(payload["Amount"], 2000)
        self.assertEqual(payload["InitiatorName"], "testapi")
        self.assertEqual(payload["ResultURL"], "https://hotel.example.com/payments/callbacks/b2c/result/tok123/")
        self.assertEqual(refund.status, refund.Status.PENDING)
        self.assertEqual(self.booking.payments_total, Decimal("5000"))  # nothing recorded until confirmed

        url = reverse("mpesa:b2c_result", args=["tok123"])
        body = json.dumps(b2c_result(refund.originator_conversation_id))
        self.client.post(url, data=body, content_type="application/json")
        self.client.post(url, data=body, content_type="application/json")  # duplicate
        refund.refresh_from_db()
        self.assertEqual(refund.status, refund.Status.SUCCESS)
        self.assertEqual(refund.transaction_id, "NLJ41HAY6Q")
        self.assertEqual(Payment.objects.filter(kind=Payment.Kind.REFUND).count(), 1)
        self.assertEqual(self.booking.payments_total, Decimal("3000"))

    @override_settings(**B2C_LIVE)
    def test_failed_and_timed_out_refunds(self):
        from mpesa.models import B2CRefund

        failed = B2CRefund.objects.create(booking=self.booking, phone="254712345678", amount=1000, reason="x",
                                          originator_conversation_id="o-fail")
        self.client.post(reverse("mpesa:b2c_result", args=["tok123"]),
                         data=json.dumps(b2c_result("o-fail", code=2001)), content_type="application/json")
        failed.refresh_from_db()
        self.assertEqual(failed.status, B2CRefund.Status.FAILED)
        slow = B2CRefund.objects.create(booking=self.booking, phone="254712345678", amount=1000, reason="x",
                                        originator_conversation_id="o-slow")
        self.client.post(reverse("mpesa:b2c_timeout", args=["tok123"]),
                         data=json.dumps({"Result": {"OriginatorConversationID": "o-slow"}}),
                         content_type="application/json")
        slow.refresh_from_db()
        self.assertEqual(slow.status, B2CRefund.Status.FAILED)
        self.assertEqual(Payment.objects.filter(kind=Payment.Kind.REFUND).count(), 0)
        resp = self.client.post(reverse("mpesa:b2c_result", args=["wrong"]), data="{}", content_type="application/json")
        self.assertEqual(resp.status_code, 404)

    @override_settings(MPESA_SIMULATE=False, MPESA_B2C_INITIATOR_NAME="", MPESA_B2C_SECURITY_CREDENTIAL="")
    def test_refunds_off_without_credentials(self):
        with self.assertRaisesMessage(services.MpesaError, "not set up"):
            services.initiate_refund(booking=self.booking, phone="0712345678", amount=100, reason="x")

    @override_settings(MPESA_SIMULATE=True)
    def test_only_finance_can_send_refunds(self):
        self.login(self.reception)
        resp = self.client.post(reverse("mpesa:refund_start"), {"booking": self.booking.pk, "phone": "0712345678",
                                                                 "amount": "100", "reason": "x"})
        self.assertEqual(resp.status_code, 403)
        self.login(self.accountant)
        self.client.post(reverse("mpesa:refund_start"), {"booking": self.booking.pk, "phone": "0712345678",
                                                         "amount": "100", "reason": "Goodwill"})
        self.assertEqual(self.booking.payments_total, Decimal("4900"))
        self.assertContains(self.client.get(reverse("mpesa:refund_list")), "Goodwill")
