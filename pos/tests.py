from decimal import Decimal

from django.urls import reverse

from bookings.models import Booking, Charge
from bookings.services import BookingError
from hoteli.testutils import HotelTestCase
from pos import services
from pos.models import MenuCategory, MenuItem, Order


class PosTests(HotelTestCase):
    def setUp(self):
        super().setUp()
        cat = MenuCategory.objects.create(name="Mains")
        self.food = MenuItem.objects.create(category=cat, name="Nyama choma", price=Decimal("1200"), kind="FOOD")
        self.beer = MenuItem.objects.create(category=cat, name="Tusker", price=Decimal("350"), kind="BEVERAGE")

    def test_charge_to_room_splits_food_and_beverage(self):
        booking = self.make_booking(ci=-1, co=1, status=Booking.Status.CHECKED_IN)
        order = Order.objects.create(booking=booking, outlet=Order.Outlet.RESTAURANT, discount=Decimal("100"))
        services.add_item(order, self.food, 2)
        services.add_item(order, self.beer, 3)
        services.add_item(order, self.beer, 1)  # merges into the same line
        self.assertEqual(order.items.count(), 2)
        services.charge_to_room(order)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CHARGED)
        self.assertEqual(booking.charges.get(category=Charge.Category.FOOD).amount, Decimal("2400"))
        self.assertEqual(booking.charges.get(category=Charge.Category.BEVERAGE).amount, Decimal("1400"))
        self.assertEqual(booking.charges_total, Decimal("3700"))
        services.cancel_order(order, reason="Wrong room")
        self.assertEqual(booking.charges_total, Decimal("0"))

    def test_charge_to_room_requires_in_house_guest(self):
        booking = self.make_booking(ci=1, co=2)
        order = Order.objects.create(booking=booking)
        services.add_item(order, self.food)
        with self.assertRaisesMessage(BookingError, "in-house"):
            services.charge_to_room(order)

    def test_cash_payment_closes_order(self):
        order = Order.objects.create()
        services.add_item(order, self.beer, 2)
        self.login(self.waiter)
        self.client.post(reverse("pos:order_pay", args=[order.pk]), {"method": "CASH", "amount": "300"})
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.OPEN)
        self.client.post(reverse("pos:order_pay", args=[order.pk]), {"method": "CASH", "amount": "400"})
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)
        self.assertEqual(order.balance, Decimal("0"))

    def test_waiter_views(self):
        self.login(self.waiter)
        resp = self.client.post(reverse("pos:order_create"), {"outlet": "BAR"})
        order = Order.objects.get()
        self.assertRedirects(resp, reverse("pos:order", args=[order.pk]))
        self.client.post(reverse("pos:order_add_item", args=[order.pk]), {"item": self.food.pk})
        self.assertContains(self.client.get(reverse("pos:order", args=[order.pk])), "Nyama choma")
        self.assertEqual(self.client.get(reverse("pos:order_bill", args=[order.pk])).status_code, 200)
