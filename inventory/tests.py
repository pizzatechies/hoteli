from decimal import Decimal

from django.urls import reverse

from bookings.models import Booking
from finance.models import Expense
from hoteli.testutils import HotelTestCase
from inventory import services
from inventory.models import StockItem
from pos import services as pos
from pos.models import MenuCategory, MenuItem, Order


class StockTests(HotelTestCase):
    def setUp(self):
        super().setUp()
        self.tusker = StockItem.objects.create(name="Tusker 500ml", unit="bottle", reorder_level=Decimal("10"))
        cat = MenuCategory.objects.create(name="Drinks")
        self.beer = MenuItem.objects.create(category=cat, name="Tusker", price=Decimal("350"), kind="BEVERAGE",
                                            stock_item=self.tusker, stock_quantity=Decimal("1"))

    def test_receiving_stock_records_an_expense(self):
        services.receive(self.tusker, 48, Decimal("180"), supplier="EABL depot")
        self.tusker.refresh_from_db()
        self.assertEqual(self.tusker.quantity, Decimal("48"))
        self.assertEqual(self.tusker.unit_cost, Decimal("180"))
        expense = Expense.objects.get()
        self.assertEqual((expense.amount, expense.category), (Decimal("8640.00"), Expense.Category.FOOD_BEVERAGE))

    def test_paid_order_deducts_once_and_cancel_restores(self):
        services.receive(self.tusker, 12, Decimal("180"), record_expense=False)
        order = Order.objects.create()
        pos.add_item(order, self.beer, 3)
        from bookings.services import record_payment

        record_payment(order=order, amount=Decimal("1050"), method="CASH")
        self.tusker.refresh_from_db()
        self.assertEqual(self.tusker.quantity, Decimal("9"))
        self.assertTrue(self.tusker.is_low)  # 9 <= reorder level 10
        services.deduct_order(order)  # second call does nothing
        self.tusker.refresh_from_db()
        self.assertEqual(self.tusker.quantity, Decimal("9"))

    def test_charge_to_room_deducts_and_cancel_returns_stock(self):
        services.receive(self.tusker, 5, Decimal("180"), record_expense=False)
        booking = self.make_booking(ci=-1, co=1, status=Booking.Status.CHECKED_IN)
        order = Order.objects.create(booking=booking)
        pos.add_item(order, self.beer, 2)
        pos.charge_to_room(order)
        self.tusker.refresh_from_db()
        self.assertEqual(self.tusker.quantity, Decimal("3"))
        pos.cancel_order(order, reason="Wrong room")
        self.tusker.refresh_from_db()
        self.assertEqual(self.tusker.quantity, Decimal("5"))

    def test_stock_count_and_waste(self):
        services.receive(self.tusker, 20, Decimal("180"), record_expense=False)
        services.count(self.tusker, 18, note="Monthly count")
        services.move(self.tusker, "WASTE", -1, note="Broken")
        self.tusker.refresh_from_db()
        self.assertEqual(self.tusker.quantity, Decimal("17"))
        self.assertEqual(list(self.tusker.movements.values_list("kind", flat=True)), ["WASTE", "COUNT", "PURCHASE"])

    def test_screens_and_permissions(self):
        self.login(self.waiter)
        resp = self.client.post(reverse("inventory:receive", args=[self.tusker.pk]),
                                {"quantity": "24", "unit_cost": "180", "method": "CASH", "record_expense": "on"})
        self.assertRedirects(resp, reverse("inventory:list"))
        self.assertContains(self.client.get(reverse("inventory:list")), "Tusker 500ml")
        self.assertContains(self.client.get(reverse("inventory:detail", args=[self.tusker.pk])), "Received")
        self.assertEqual(self.client.get(reverse("inventory:create")).status_code, 403)  # managers add items
        self.login(self.hk)
        self.assertEqual(self.client.get(reverse("inventory:list")).status_code, 403)
