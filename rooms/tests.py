from decimal import Decimal

from django.urls import reverse

from bookings.models import Booking
from hoteli.testutils import HotelTestCase
from rooms.models import CorporateAccount, PromoCode, StayDiscount
from rooms.pricing import quote


class PricingTests(HotelTestCase):
    def test_percent_and_amount_promos(self):
        PromoCode.objects.create(code="karibu10", percent_off=Decimal("10"))
        PromoCode.objects.create(code="FLAT", amount_off=Decimal("1500"))
        q = quote(self.std, self.day(1), self.day(3), promo_code=" Karibu10 ")
        self.assertEqual((q.base_total, q.discount_total, q.total), (Decimal("10000"), Decimal("1000"), Decimal("9000")))
        self.assertEqual(q.nightly, Decimal("4500.00"))
        self.assertEqual(quote(self.std, self.day(1), self.day(3), promo_code="flat").total, Decimal("8500"))

    def test_promo_rules(self):
        promo = PromoCode.objects.create(code="SUITE", percent_off=Decimal("20"), min_nights=2, max_uses=1,
                                         valid_until=self.day(5), on_website=False)
        promo.room_types.add(self.suite)
        self.assertIn("isn't valid for Standard", quote(self.std, self.day(1), self.day(3), promo_code="SUITE").promo_error)
        self.assertIn("at least 2 nights", quote(self.suite, self.day(1), self.day(2), promo_code="SUITE").promo_error)
        self.assertIn("expired", quote(self.suite, self.day(6), self.day(8), promo_code="SUITE").promo_error)
        self.assertIn("isn't valid", quote(self.suite, self.day(1), self.day(3), promo_code="SUITE", website=True).promo_error)
        self.assertEqual(quote(self.suite, self.day(1), self.day(3), promo_code="SUITE").discount_total, Decimal("4800"))
        promo.times_used = 1
        promo.save()
        self.assertIn("fully used", quote(self.suite, self.day(1), self.day(3), promo_code="SUITE").promo_error)

    def test_best_single_discount_wins(self):
        StayDiscount.objects.create(min_nights=3, percent_off=Decimal("15"))
        PromoCode.objects.create(code="TEN", percent_off=Decimal("10"))
        q = quote(self.std, self.day(1), self.day(4), promo_code="TEN")
        self.assertEqual(q.discount_total, Decimal("2250"))  # 15% long stay beats the 10% code; no stacking
        self.assertIn("Long-stay", q.discount_label)
        self.assertIsNone(q.promo)

    def test_corporate_rate_and_booking_records_discount(self):
        company = CorporateAccount.objects.create(name="Safari Telecom", percent_off=Decimal("12"))
        self.login(self.reception)
        self.client.post(reverse("bookings:create"), {
            "guest": self.guest.pk, "check_in_date": self.today, "check_out_date": self.day(2), "adults": 1,
            "children": 0, "room": self.r101.pk, "source": "CORPORATE", "status": "CONFIRMED",
            "corporate_account": company.pk,
        })
        b = Booking.objects.get()
        self.assertEqual(b.corporate_account, company)
        self.assertEqual(b.rate, Decimal("4400.00"))
        self.assertEqual(b.base_rate, Decimal("5000.00"))
        self.assertIn("Safari Telecom", b.discount_label)
        self.assertContains(self.client.get(reverse("bookings:invoice", args=[b.pk])), "Safari Telecom")

    def test_staff_invalid_promo_shows_error(self):
        self.login(self.reception)
        resp = self.client.post(reverse("bookings:create"), {
            "guest": self.guest.pk, "check_in_date": self.today, "check_out_date": self.day(1), "adults": 1,
            "children": 0, "room": self.r101.pk, "source": "PHONE", "status": "CONFIRMED", "promo_code": "NOPE",
        })
        self.assertContains(resp, "isn&#x27;t valid")
        self.assertFalse(Booking.objects.exists())

    def test_website_booking_with_promo_counts_use(self):
        promo = PromoCode.objects.create(code="WEB20", percent_off=Decimal("20"), max_uses=5)
        params = {"check_in": self.day(1).isoformat(), "check_out": self.day(3).isoformat(), "adults": 2,
                  "children": 0, "promo": "web20"}
        resp = self.client.get(reverse("website:search"), params)
        self.assertContains(resp, "8,000")
        self.assertContains(resp, "Promo WEB20")
        url = reverse("website:book", args=[self.std.pk]) + "?" + "&".join(f"{k}={v}" for k, v in params.items())
        self.client.post(url, {"first_name": "Amina", "last_name": "Ali", "phone": "0722000111",
                               "email": "amina@example.com", "accept_terms": "on"})
        b = Booking.objects.get()
        self.assertEqual(b.promo_code, promo)
        self.assertEqual(b.deposit_required, Decimal("4000"))  # 50% of the discounted 8,000
        promo.refresh_from_db()
        self.assertEqual(promo.times_used, 1)

    def test_manager_screens(self):
        self.login(self.manager)
        resp = self.client.post(reverse("rooms:promo_create"), {"code": "easter", "percent_off": "15", "min_nights": 1,
                                                                "on_website": "on", "is_active": "on"})
        self.assertRedirects(resp, reverse("rooms:types"))
        self.assertTrue(PromoCode.objects.filter(code="EASTER").exists())
        resp = self.client.post(reverse("rooms:promo_create"), {"code": "BOTH", "percent_off": "5", "amount_off": "100",
                                                                "min_nights": 1})
        self.assertContains(resp, "not both")
        self.assertContains(self.client.get(reverse("rooms:types")), "EASTER")
        self.login(self.reception)
        self.assertEqual(self.client.get(reverse("rooms:promo_create")).status_code, 403)


