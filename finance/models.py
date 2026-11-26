from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Expense(models.Model):
    class Category(models.TextChoices):
        FOOD_BEVERAGE = "FOOD_BEVERAGE", "Food & beverage purchases"
        SALARIES = "SALARIES", "Salaries & wages"
        UTILITIES = "UTILITIES", "Electricity, water & gas"
        RENT = "RENT", "Rent & rates"
        MAINTENANCE = "MAINTENANCE", "Repairs & maintenance"
        SUPPLIES = "SUPPLIES", "Housekeeping & guest supplies"
        COMMISSIONS = "COMMISSIONS", "Booking commissions (OTAs)"
        MARKETING = "MARKETING", "Marketing"
        INTERNET = "INTERNET", "Internet & phone"
        TRANSPORT = "TRANSPORT", "Transport & fuel"
        TAXES = "TAXES", "Taxes, licences & levies"
        BANK = "BANK", "Bank & M-Pesa charges"
        OTHER = "OTHER", "Other"

    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        MPESA = "MPESA", "M-Pesa"
        BANK = "BANK", "Bank transfer"
        CARD = "CARD", "Card"
        CHEQUE = "CHEQUE", "Cheque"
        CREDIT = "CREDIT", "On credit (unpaid)"

    date = models.DateField(default=timezone.localdate)
    category = models.CharField(max_length=15, choices=Category.choices, default=Category.OTHER)
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    method = models.CharField("Paid by", max_length=8, choices=Method.choices, default=Method.CASH)
    supplier = models.CharField(max_length=120, blank=True)
    reference = models.CharField(max_length=60, blank=True, help_text="Receipt / invoice / M-Pesa code")
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.date} {self.get_category_display()} {self.amount}"
