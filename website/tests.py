from decimal import Decimal

from django.core import mail
from django.test import override_settings
from django.urls import reverse

from bookings.models import Booking
from core.models import HotelSettings
from hoteli.testutils import HotelTestCase
from mpesa.models import MpesaTransaction
from website.models import ContactMessage


@override_settings(MPESA_SIMULATE=True)
class WebsiteBookingTests(HotelTestCase):
    def search_params(self, ci=1, co=3, adults=2):
        return {"check_in": self.day(ci).isoformat(), "check_out": self.day(co).isoformat(),
                "adults": adults, "children": 0}

    def guest_data(self, **extra):
        return {"first_name": "Wanjiru", "last_name": "Kamau", "phone": "0722 000 111",
                "email": "wanjiru@example.com", "accept_terms": "on", **extra}

    def test_public_pages(self):
        for name in ["home", "rooms", "dining", "facilities", "contact", "search", "lookup"]:
            self.assertEqual(self.client.get(reverse(f"website:{name}")).status_code, 200, name)
        self.assertContains(self.client.get(reverse("website:room_detail", args=[self.std.pk])), "Standard")

    def test_search_lists_available_types_with_quote(self):
        resp = self.client.get(reverse("website:search"), self.search_params())
        self.assertContains(resp, "Standard")
        self.assertContains(resp, "10,000")  # 2 nights x 5,000

    def test_search_rejects_past_dates(self):
        resp = self.client.get(reverse("website:search"), self.search_params(ci=-1, co=1))
        self.assertContains(resp, "cannot be in the past")

    def test_full_online_booking_with_mpesa_deposit(self):
        url = reverse("website:book", args=[self.std.pk]) + "?" + "&".join(
            f"{k}={v}" for k, v in self.search_params().items())
        resp = self.client.post(url, self.guest_data())
        booking = Booking.objects.get(source=Booking.Source.WEBSITE)
        self.assertRedirects(resp, reverse("website:booking", args=[booking.public_token]))
        self.assertEqual(booking.status, Booking.Status.PENDING)
        self.assertEqual(booking.deposit_required, Decimal("5000"))  # 50% of 10,000
        self.assertIsNotNone(booking.expires_at)

        page = self.client.get(reverse("website:booking", args=[booking.public_token]))
        self.assertContains(page, "Pay your deposit")

        resp = self.client.post(reverse("website:booking_pay", args=[booking.public_token]),
                                {"phone": "0722000111", "amount": "1"}, HTTP_ACCEPT="application/json")
        tx = MpesaTransaction.objects.get(uuid=resp.json()["id"])
        self.assertEqual(tx.amount, Decimal("5000"))  # deposit amount enforced server-side
        self.assertEqual(tx.source, MpesaTransaction.Source.WEBSITE)

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("mpesa:simulate", args=[tx.uuid]), {"outcome": "success"})
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertContains(self.client.get(reverse("website:booking", args=[booking.public_token])),
                            "Your booking is confirmed")

    def test_no_deposit_mode_confirms_immediately(self):
        hotel = HotelSettings.objects.get_or_create(pk=1)[0]
        hotel.website_require_deposit = False
        hotel.save()
        url = reverse("website:book", args=[self.std.pk]) + "?" + "&".join(
            f"{k}={v}" for k, v in self.search_params().items())
        self.client.post(url, self.guest_data())
        self.assertEqual(Booking.objects.get().status, Booking.Status.CONFIRMED)

    def test_sold_out_message(self):
        self.make_booking(room=self.r101, ci=1, co=3)
        self.make_booking(room=self.r102, ci=1, co=3)
        url = reverse("website:book", args=[self.std.pk]) + "?" + "&".join(
            f"{k}={v}" for k, v in self.search_params().items())
        resp = self.client.post(url, self.guest_data())
        self.assertContains(resp, "sold out")

    def test_existing_guest_is_reused(self):
        url = reverse("website:book", args=[self.std.pk]) + "?" + "&".join(
            f"{k}={v}" for k, v in self.search_params().items())
        self.client.post(url, self.guest_data(first_name="Jane", email="jane@example.com", phone="+254712345678"))
        self.assertEqual(Booking.objects.get().guest, self.guest)

    def test_honeypot_blocks_bots(self):
        url = reverse("website:book", args=[self.std.pk]) + "?" + "&".join(
            f"{k}={v}" for k, v in self.search_params().items())
        self.client.post(url, self.guest_data(website="http://spam"))
        self.assertFalse(Booking.objects.exists())

    def test_lookup_by_phone_in_any_format(self):
        booking = self.make_booking(ci=1, co=2)
        resp = self.client.post(reverse("website:lookup"), {"reference": booking.reference.lower(),
                                                            "contact": "+254 712 345 678"})
        self.assertRedirects(resp, reverse("website:booking", args=[booking.public_token]))
        resp = self.client.post(reverse("website:lookup"), {"reference": booking.reference, "contact": "0799999999"})
        self.assertContains(resp, "couldn&#x27;t find")

    def test_contact_form(self):
        self.client.post(reverse("website:contact"), {"name": "Tom", "email": "tom@example.com", "subject": "Hi",
                                                      "message": "Do you have a pool?"})
        self.assertEqual(ContactMessage.objects.count(), 1)
        self.login(self.reception)
        self.assertContains(self.client.get(reverse("website:inbox")), "Do you have a pool?")
