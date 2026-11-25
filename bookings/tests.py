import datetime
from decimal import Decimal

from django.core import mail
from django.urls import reverse
from django.utils import timezone

from bookings import services
from bookings.models import Booking, Charge, Guest, NightAuditRun, Payment
from bookings.services import BookingError
from core.models import HotelSettings
from hoteli.testutils import HotelTestCase
from housekeeping.models import HousekeepingTask
from rooms.models import Room, SeasonalRate


class AvailabilityTests(HotelTestCase):
    def test_back_to_back_stays_are_allowed(self):
        services.create_booking(guest=self.guest, room=self.r101, check_in=self.day(1), check_out=self.day(3))
        b2 = services.create_booking(guest=self.guest, room=self.r101, check_in=self.day(3), check_out=self.day(5))
        self.assertEqual(b2.nights, 2)

    def test_overlapping_stay_is_rejected(self):
        services.create_booking(guest=self.guest, room=self.r101, check_in=self.day(1), check_out=self.day(4))
        with self.assertRaisesMessage(BookingError, "already booked"):
            services.create_booking(guest=self.guest, room=self.r101, check_in=self.day(3), check_out=self.day(6))

    def test_cancelled_booking_frees_the_room(self):
        b = services.create_booking(guest=self.guest, room=self.r101, check_in=self.day(1), check_out=self.day(4))
        services.cancel_booking(b, reason="Plans changed")
        self.assertTrue(services.available_rooms(self.day(1), self.day(4)).filter(pk=self.r101.pk).exists())

    def test_capacity_is_enforced(self):
        with self.assertRaisesMessage(BookingError, "at most 2 adult"):
            services.create_booking(guest=self.guest, room=self.r101, check_in=self.day(1), check_out=self.day(2), adults=3)

    def test_out_of_order_room_cannot_be_booked_for_today(self):
        Room.objects.filter(pk=self.r101.pk).update(is_out_of_order=True, out_of_order_reason="Leak")
        with self.assertRaisesMessage(BookingError, "out of order"):
            services.create_booking(guest=self.guest, room=self.r101, check_in=self.today, check_out=self.day(1))
        self.assertFalse(services.available_rooms(self.today, self.day(1)).filter(pk=self.r101.pk).exists())

    def test_blacklisted_guest_cannot_book(self):
        self.guest.is_blacklisted = True
        self.guest.blacklist_reason = "Damaged room"
        self.guest.save()
        with self.assertRaisesMessage(BookingError, "blacklisted"):
            services.create_booking(guest=self.guest, room=self.r101, check_in=self.day(1), check_out=self.day(2))

    def test_seasonal_rate_used_in_quote_and_default_rate(self):
        SeasonalRate.objects.create(room_type=self.std, name="Peak", start_date=self.day(1), end_date=self.day(1),
                                    rate=Decimal("8000"))
        self.assertEqual(self.std.quote(self.day(0), self.day(2)), Decimal("13000"))
        b = services.create_booking(guest=self.guest, room=self.r101, check_in=self.day(0), check_out=self.day(2))
        self.assertEqual(b.rate, Decimal("6500.00"))

    def test_availability_by_room_type_respects_party_size(self):
        results = services.availability_by_room_type(self.day(1), self.day(2), adults=3)
        self.assertEqual([r["room_type"] for r in results], [self.suite])


class CheckInOutTests(HotelTestCase):
    def test_check_in_requires_id_number(self):
        self.guest.id_number = ""
        self.guest.save()
        b = self.make_booking()
        with self.assertRaisesMessage(BookingError, "ID or passport"):
            services.check_in(b)

    def test_check_in_blocks_dirty_room_unless_overridden(self):
        Room.objects.filter(pk=self.r101.pk).update(hk_status=Room.HKStatus.DIRTY)
        b = self.make_booking()
        with self.assertRaisesMessage(BookingError, "dirty"):
            services.check_in(b)
        services.check_in(b, override_dirty=True)
        b.refresh_from_db()
        self.assertEqual(b.status, Booking.Status.CHECKED_IN)

    def test_cannot_check_in_future_arrival(self):
        b = self.make_booking(ci=2, co=4)
        with self.assertRaisesMessage(BookingError, "Arrival is on"):
            services.check_in(b)

    def test_cannot_check_in_to_occupied_room(self):
        self.make_booking(ci=-2, co=0, status=Booking.Status.CHECKED_IN)  # overstaying guest
        b = self.make_booking(ci=0, co=2)
        with self.assertRaisesMessage(BookingError, "still occupied"):
            services.check_in(b)

    def test_late_arrival_moves_check_in_date(self):
        b = self.make_booking(ci=-1, co=2)
        services.check_in(b)
        b.refresh_from_db()
        self.assertEqual(b.check_in_date, self.today)
        self.assertIn("Late arrival", b.internal_notes)

    def test_check_out_posts_charges_and_requires_payment(self):
        b = self.make_booking(ci=-2, co=0, status=Booking.Status.CHECKED_IN)
        with self.assertRaisesMessage(BookingError, "Outstanding balance"):
            services.check_out(b)
        # posting is rolled back with the failed check-out
        self.assertEqual(b.charges.count(), 0)
        services.record_payment(booking=b, amount=Decimal("10000"), method=Payment.Method.CASH)
        services.check_out(b)
        b.refresh_from_db()
        self.assertEqual(b.status, Booking.Status.CHECKED_OUT)
        self.assertEqual(b.charges.filter(category=Charge.Category.ROOM).count(), 2)
        self.assertEqual(b.balance, Decimal("0"))
        self.r101.refresh_from_db()
        self.assertEqual(self.r101.hk_status, Room.HKStatus.DIRTY)
        self.assertTrue(HousekeepingTask.objects.filter(room=self.r101, booking=b).exists())

    def test_manager_override_allows_balance(self):
        b = self.make_booking(ci=-1, co=0, status=Booking.Status.CHECKED_IN)
        services.check_out(b, allow_balance=True)
        b.refresh_from_db()
        self.assertEqual(b.status, Booking.Status.CHECKED_OUT)
        self.assertEqual(b.balance, Decimal("5000"))

    def test_early_departure_shortens_stay(self):
        b = self.make_booking(ci=-1, co=3, status=Booking.Status.CHECKED_IN)
        services.check_out(b, allow_balance=True)
        b.refresh_from_db()
        self.assertEqual(b.check_out_date, self.today)
        self.assertEqual(b.charges.count(), 1)
        self.assertIn("Early departure", b.internal_notes)

    def test_same_day_checkout_charges_minimum_one_night(self):
        b = self.make_booking(ci=0, co=2)
        services.check_in(b)
        services.check_out(b, allow_balance=True)
        b.refresh_from_db()
        self.assertEqual(b.check_out_date, self.day(1))
        self.assertEqual(b.charges_total, Decimal("5000"))


class NightAuditTests(HotelTestCase):
    def test_night_audit_posts_once_and_marks_no_shows(self):
        inhouse = self.make_booking(ci=-1, co=2, status=Booking.Status.CHECKED_IN)
        no_show = self.make_booking(room=self.r102, ci=-1, co=1)
        services.night_audit()
        services.night_audit()  # idempotent
        self.assertEqual(inhouse.charges.filter(category=Charge.Category.ROOM).count(), 2)
        no_show.refresh_from_db()
        self.assertEqual(no_show.status, Booking.Status.NO_SHOW)
        self.assertEqual(NightAuditRun.objects.get().room_charges_posted, 2)

    def test_overstaying_guest_is_extended(self):
        b = self.make_booking(ci=-2, co=0, status=Booking.Status.CHECKED_IN)
        services.night_audit()
        b.refresh_from_db()
        self.assertEqual(b.check_out_date, self.day(1))
        self.assertEqual(b.charges.count(), 3)


class HoldExpiryTests(HotelTestCase):
    def test_unpaid_hold_is_released(self):
        b = self.make_booking(ci=1, co=2, status=Booking.Status.PENDING,
                              expires_at=timezone.now() - datetime.timedelta(minutes=1), deposit_required=Decimal("2500"))
        self.assertEqual(services.expire_pending_holds(), 1)
        b.refresh_from_db()
        self.assertEqual(b.status, Booking.Status.CANCELLED)

    def test_payment_after_expiry_reinstates_booking(self):
        b = self.make_booking(ci=1, co=2, status=Booking.Status.PENDING,
                              expires_at=timezone.now() - datetime.timedelta(minutes=1), deposit_required=Decimal("2500"))
        services.expire_pending_holds()
        services.record_payment(booking=b, amount=Decimal("2500"), method=Payment.Method.MPESA, reference="QWE123RTY")
        b.refresh_from_db()
        self.assertEqual(b.status, Booking.Status.CONFIRMED)
        self.assertIn("Reinstated", b.internal_notes)

    def test_late_payment_when_room_taken_flags_for_refund(self):
        b = self.make_booking(ci=1, co=2, status=Booking.Status.PENDING,
                              expires_at=timezone.now() - datetime.timedelta(minutes=1), deposit_required=Decimal("2500"))
        services.expire_pending_holds()
        self.make_booking(room=self.r101, ci=1, co=2)
        self.make_booking(room=self.r102, ci=1, co=2)
        services.record_payment(booking=b, amount=Decimal("2500"), method=Payment.Method.MPESA, reference="ZXC123VBN")
        b.refresh_from_db()
        self.assertEqual(b.status, Booking.Status.CANCELLED)
        self.assertIn("refund", b.internal_notes)

    def test_deposit_confirms_pending_booking_and_emails_guest(self):
        b = self.make_booking(ci=1, co=3, status=Booking.Status.PENDING, deposit_required=Decimal("5000"),
                              expires_at=timezone.now() + datetime.timedelta(minutes=30))
        with self.captureOnCommitCallbacks(execute=True):
            services.record_payment(booking=b, amount=Decimal("2000"), method=Payment.Method.CASH)
        b.refresh_from_db()
        self.assertEqual(b.status, Booking.Status.PENDING)
        with self.captureOnCommitCallbacks(execute=True):
            services.record_payment(booking=b, amount=Decimal("3000"), method=Payment.Method.CASH)
        b.refresh_from_db()
        self.assertEqual(b.status, Booking.Status.CONFIRMED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(b.reference, mail.outbox[0].subject)


class FolioTests(HotelTestCase):
    def test_duplicate_mpesa_code_rejected(self):
        b = self.make_booking()
        services.record_payment(booking=b, amount=Decimal("100"), method=Payment.Method.MPESA, reference="ABC123XYZ")
        with self.assertRaisesMessage(BookingError, "already recorded"):
            services.record_payment(booking=b, amount=Decimal("100"), method=Payment.Method.MPESA, reference="abc123xyz")

    def test_refund_cannot_exceed_paid(self):
        b = self.make_booking()
        services.record_payment(booking=b, amount=Decimal("1000"), method=Payment.Method.CASH)
        with self.assertRaisesMessage(BookingError, "Refund cannot exceed"):
            services.record_payment(booking=b, amount=Decimal("1500"), method=Payment.Method.CASH,
                                    kind=Payment.Kind.REFUND)
        services.record_payment(booking=b, amount=Decimal("400"), method=Payment.Method.CASH, kind=Payment.Kind.REFUND)
        self.assertEqual(b.payments_total, Decimal("600"))

    def test_discount_is_negative_and_void_excluded(self):
        b = self.make_booking()
        services.post_charge(b, category=Charge.Category.MINIBAR, description="Water", unit_price=Decimal("200"), quantity=2)
        d = services.post_charge(b, category=Charge.Category.DISCOUNT, description="Goodwill", unit_price=Decimal("100"))
        self.assertEqual(d.amount, Decimal("-100.00"))
        self.assertEqual(b.charges_total, Decimal("300"))
        services.void_charge(d, reason="Mistake")
        self.assertEqual(b.charges_total, Decimal("400"))

    def test_room_charges_cannot_be_posted_manually(self):
        with self.assertRaises(BookingError):
            services.post_charge(self.make_booking(), category=Charge.Category.ROOM, description="x", unit_price=1)

    def test_projected_total_and_with_totals_annotation(self):
        b = self.make_booking(ci=0, co=3)
        services.post_charge(b, category=Charge.Category.LAUNDRY, description="Laundry", unit_price=Decimal("500"))
        services.record_payment(booking=b, amount=Decimal("5000"), method=Payment.Method.CASH)
        self.assertEqual(b.projected_total(), Decimal("15500"))
        self.assertEqual(b.projected_balance(), Decimal("10500"))
        annotated = Booking.objects.with_totals().get(pk=b.pk)
        self.assertEqual(annotated.charges_total, Decimal("500"))
        self.assertEqual(annotated.payments_total, Decimal("5000"))

    def test_shortening_stay_below_posted_nights_blocked(self):
        b = self.make_booking(ci=-2, co=3, status=Booking.Status.CHECKED_IN)
        services.post_room_charges(b, up_to=self.day(1))
        with self.assertRaisesMessage(BookingError, "Check out"):
            services.update_booking(b, room=self.r101, check_in=b.check_in_date, check_out=self.today,
                                    adults=1, children=0, rate=b.rate)

    def test_room_move_marks_old_room_dirty(self):
        b = self.make_booking(ci=-1, co=2, status=Booking.Status.CHECKED_IN)
        services.update_booking(b, room=self.r102, check_in=b.check_in_date, check_out=b.check_out_date,
                                adults=1, children=0, rate=b.rate)
        self.r101.refresh_from_db()
        self.assertEqual(self.r101.hk_status, Room.HKStatus.DIRTY)


class BookingViewTests(HotelTestCase):
    def test_create_booking_with_new_guest(self):
        self.login(self.reception)
        resp = self.client.post(reverse("bookings:create"), {
            "first_name": "Ali", "last_name": "Hassan", "phone": "0700111222", "id_type": "NATIONAL_ID",
            "id_number": "99887766", "nationality": "Kenyan", "check_in_date": self.today, "check_out_date": self.day(2),
            "adults": 1, "children": 0, "room": self.r102.pk, "source": "WALK_IN", "status": "CONFIRMED",
        })
        booking = Booking.objects.get(guest__first_name="Ali")
        self.assertRedirects(resp, reverse("bookings:detail", args=[booking.pk]))
        self.assertEqual(booking.rate, Decimal("5000.00"))

    def test_failed_booking_does_not_leave_orphan_guest(self):
        self.make_booking(room=self.r102, ci=0, co=3)
        self.login(self.reception)
        before = Guest.objects.count()
        resp = self.client.post(reverse("bookings:create"), {
            "first_name": "Ali", "last_name": "Hassan", "phone": "0700111222", "check_in_date": self.today,
            "check_out_date": self.day(2), "adults": 1, "children": 0, "room": self.r102.pk, "source": "WALK_IN",
            "status": "CONFIRMED", "id_type": "NATIONAL_ID", "nationality": "Kenyan",
        })
        self.assertContains(resp, "already booked")
        self.assertEqual(Guest.objects.count(), before)

    def test_check_in_and_out_through_views(self):
        b = self.make_booking(ci=0, co=1)
        self.login(self.reception)
        self.client.post(reverse("bookings:check_in", args=[b.pk]))
        b.refresh_from_db()
        self.assertEqual(b.status, Booking.Status.CHECKED_IN)
        self.client.post(reverse("bookings:payment_add", args=[b.pk]), {"method": "CASH", "amount": "5000"})
        self.client.post(reverse("bookings:check_out", args=[b.pk]))
        b.refresh_from_db()
        self.assertEqual(b.status, Booking.Status.CHECKED_OUT)

    def test_receptionist_cannot_override_balance_but_manager_can(self):
        b = self.make_booking(ci=-1, co=0, status=Booking.Status.CHECKED_IN)
        self.login(self.reception)
        self.client.post(reverse("bookings:check_out", args=[b.pk]), {"allow_balance": "1"})
        b.refresh_from_db()
        self.assertEqual(b.status, Booking.Status.CHECKED_IN)
        self.login(self.manager)
        self.client.post(reverse("bookings:check_out", args=[b.pk]), {"allow_balance": "1"})
        b.refresh_from_db()
        self.assertEqual(b.status, Booking.Status.CHECKED_OUT)

    def test_role_permissions(self):
        self.login(self.hk)
        self.assertEqual(self.client.get(reverse("bookings:list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("housekeeping:board")).status_code, 200)
        self.login(self.waiter)
        self.assertEqual(self.client.get(reverse("core:reports")).status_code, 403)
        self.assertEqual(self.client.get(reverse("pos:home")).status_code, 200)
        self.login(self.reception)
        b = self.make_booking()
        p = services.record_payment(booking=b, amount=Decimal("10"), method=Payment.Method.CASH)
        self.assertEqual(self.client.post(reverse("bookings:payment_void", args=[p.pk]), {"reason": "x"}).status_code, 403)

    def test_tape_chart_and_availability_json(self):
        self.make_booking(ci=0, co=3)
        self.login(self.reception)
        self.assertContains(self.client.get(reverse("bookings:tape_chart")), "Jane Doe")
        data = self.client.get(reverse("bookings:availability"),
                               {"check_in": self.today, "check_out": self.day(1)}).json()
        self.assertNotIn("101", [r["number"] for r in data["rooms"]])
        self.assertIn("102", [r["number"] for r in data["rooms"]])

    def test_invoice_shows_tax_breakdown(self):
        b = self.make_booking(ci=-1, co=1, status=Booking.Status.CHECKED_IN)
        services.post_room_charges(b, up_to=self.today)
        self.login(self.reception)
        resp = self.client.get(reverse("bookings:invoice", args=[b.pk]))
        hotel = HotelSettings.load()
        tax = hotel.tax_breakdown(Decimal("5000"))
        self.assertEqual(tax["net"] + tax["vat"] + tax["levy"], Decimal("5000"))
        self.assertContains(resp, "VAT")
