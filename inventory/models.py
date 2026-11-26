from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class StockItem(models.Model):
    class Area(models.TextChoices):
        BAR = "BAR", "Bar"
        KITCHEN = "KITCHEN", "Kitchen"
        MINIBAR = "MINIBAR", "Minibar"
        HOUSEKEEPING = "HOUSEKEEPING", "Housekeeping"
        OTHER = "OTHER", "Other"

    name = models.CharField(max_length=120, unique=True)
    area = models.CharField(max_length=12, choices=Area.choices, default=Area.BAR)
    unit = models.CharField(max_length=20, default="piece", help_text="e.g. bottle, kg, litre, piece")
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    reorder_level = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"),
                                        help_text="Warn when stock falls to this level.")
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"),
                                    validators=[MinValueValidator(Decimal("0"))], help_text="Latest purchase price.")
    supplier = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["area", "name"]

    def __str__(self):
        return self.name

    @property
    def is_low(self):
        return self.is_active and self.quantity <= self.reorder_level

    @property
    def value(self):
        return (self.quantity * self.unit_cost).quantize(Decimal("0.01"))


class StockMovement(models.Model):
    class Kind(models.TextChoices):
        PURCHASE = "PURCHASE", "Received / purchased"
        SALE = "SALE", "Sold (POS)"
        WASTE = "WASTE", "Waste / breakage"
        COUNT = "COUNT", "Stock count correction"
        RETURN = "RETURN", "Returned to stock"
        USE = "USE", "Used (housekeeping/kitchen)"

    item = models.ForeignKey(StockItem, on_delete=models.CASCADE, related_name="movements")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, help_text="Positive adds stock, negative removes.")
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    note = models.CharField(max_length=200, blank=True)
    order = models.ForeignKey("pos.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} {self.quantity} {self.item}"
