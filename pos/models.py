from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Sum

ZERO = Decimal("0.00")


class MenuCategory(models.Model):
    name = models.CharField(max_length=80, unique=True)
    display_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["display_order", "name"]
        verbose_name_plural = "menu categories"

    def __str__(self):
        return self.name


class MenuItem(models.Model):
    class Kind(models.TextChoices):
        FOOD = "FOOD", "Food"
        BEVERAGE = "BEVERAGE", "Beverage"
        OTHER = "OTHER", "Other"

    category = models.ForeignKey(MenuCategory, on_delete=models.PROTECT, related_name="items")
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.FOOD)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    is_available = models.BooleanField(default=True)
    stock_item = models.ForeignKey("inventory.StockItem", null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="menu_items", help_text="Deduct this stock item when sold.")
    stock_quantity = models.DecimalField("Stock used per sale", max_digits=8, decimal_places=3, default=Decimal("1"),
                                         validators=[MinValueValidator(Decimal("0.001"))])

    class Meta:
        ordering = ["category__display_order", "category__name", "name"]
        unique_together = [("category", "name")]

    def __str__(self):
        return f"{self.name} ({self.price})"


class Order(models.Model):
    class Outlet(models.TextChoices):
        RESTAURANT = "RESTAURANT", "Restaurant"
        BAR = "BAR", "Bar"
        ROOM_SERVICE = "ROOM_SERVICE", "Room service"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CHARGED = "CHARGED", "Charged to room"
        PAID = "PAID", "Paid"
        CANCELLED = "CANCELLED", "Cancelled"

    outlet = models.CharField(max_length=15, choices=Outlet.choices, default=Outlet.RESTAURANT)
    table_number = models.CharField(max_length=20, blank=True)
    customer_name = models.CharField(max_length=120, blank=True)
    booking = models.ForeignKey(
        "bookings.Booking", null=True, blank=True, on_delete=models.PROTECT, related_name="pos_orders",
        help_text="In-house guest this order is for (required to charge to room).",
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO,
                                   validators=[MinValueValidator(Decimal("0"))])
    notes = models.CharField(max_length=255, blank=True)
    stock_deducted = models.BooleanField(default=False, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.number

    @property
    def number(self):
        return f"ORD-{self.pk:05d}" if self.pk else "ORD-new"

    @property
    def subtotal(self):
        return self.items.aggregate(t=Sum(F("quantity") * F("unit_price")))["t"] or ZERO

    @property
    def total(self):
        return max(self.subtotal - self.discount, ZERO)

    @property
    def paid_total(self):
        from bookings.models import signed_payment_sum

        return self.payments.filter(is_void=False).aggregate(t=Sum(signed_payment_sum()))["t"] or ZERO

    @property
    def balance(self):
        if self.status == self.Status.CHARGED:
            return ZERO
        return self.total - self.paid_total

    @property
    def is_open(self):
        return self.status == self.Status.OPEN


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    menu_item = models.ForeignKey(MenuItem, null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=MenuItem.Kind.choices, default=MenuItem.Kind.FOOD)
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.quantity} × {self.name}"

    @property
    def amount(self):
        return self.unit_price * self.quantity
