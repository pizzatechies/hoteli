from decimal import Decimal

from django.core import mail
from django.urls import reverse

from bookings import services
from bookings.models import Booking, Charge
from finance.daily import build_report, send_daily_report
from finance.models import Expense
from finance.reports import profit_and_loss
from hoteli.testutils import HotelTestCase
from pos import services as pos
from pos.models import MenuCategory, MenuItem, Order


class ProfitAndLossTests(HotelTestCase):
    def test_revenue_minus_expenses(self):
        b = self.make_booking(ci=-2, co=0, status=Booking.Status.CHECKED_IN)
        services.post_room_charges(b)
        services.post_charge(b, category=Charge.Category.LAUNDRY, description="Laundry", unit_price=Decimal("500"),
                             service_date=self.day(-1))
        cat = MenuCategory.objects.create(name="Bar")
        beer = MenuItem.objects.create(category=cat, name="Tusker", price=Decimal("400"), kind="BEVERAGE")
        order = Order.objects.create()
        pos.add_item(order, beer, 2)
        services.record_payment(order=order, amount=Decimal("800"), method="CASH")
        Expense.objects.create(date=self.day(-1), category=Expense.Category.UTILITIES, description="KPLC tokens",
                               amount=Decimal("3000"))
        pl = profit_and_loss(self.day(-2), self.today)
        revenue = dict(pl["revenue"])
        self.assertEqual(revenue["Room"], Decimal("10000"))
        self.assertEqual(revenue["Laundry"], Decimal("500"))
        self.assertEqual(revenue["Bar sales (walk-in)"], Decimal("800"))
        self.assertEqual(pl["total_expenses"], Decimal("3000"))
        self.assertEqual(pl["profit"], Decimal("8300"))

    def test_expense_screens_are_for_finance(self):
        self.login(self.accountant)
        resp = self.client.post(reverse("finance:expense_create"), {
            "date": self.today, "category": "SALARIES", "description": "November wages", "amount": "45000",
            "method": "BANK"})
        self.assertRedirects(resp, reverse("finance:expenses"))
        self.assertContains(self.client.get(reverse("finance:expenses")), "November wages")
        self.assertContains(self.client.get(reverse("finance:profit_loss")), "45,000")
        self.login(self.reception)
        self.assertEqual(self.client.get(reverse("finance:expenses")).status_code, 403)


class DailyReportTests(HotelTestCase):
    def test_report_goes_to_managers_with_email(self):
        self.manager.email = "mary@example.com"
        self.manager.save()
        from core.models import HotelSettings

        hotel = HotelSettings.objects.get_or_create(pk=1)[0]
        hotel.report_emails = "owner@example.com, "
        hotel.save()
        self.make_booking(ci=1, co=3)  # arrival tomorrow relative to report day = today
        b = self.make_booking(room=self.r102, ci=-1, co=1, status=Booking.Status.CHECKED_IN)
        services.post_room_charges(b, up_to=self.today)
        report = build_report(self.day(-1))
        self.assertEqual(report["stats"]["rooms_sold"], 1)
        self.assertEqual(send_daily_report(self.day(0)), 2)
        msg = mail.outbox[0]
        self.assertEqual(sorted(msg.to), ["mary@example.com", "owner@example.com"])
        self.assertIn("daily report", msg.subject)
        self.assertIn("Arrivals: 1", msg.body)
        self.assertEqual(msg.alternatives[0][1], "text/html")

    def test_no_recipients_sends_nothing(self):
        self.assertEqual(send_daily_report(), 0)
        self.assertEqual(len(mail.outbox), 0)
