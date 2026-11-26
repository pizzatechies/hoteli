from decimal import Decimal

from django import forms

from core.forms import BootstrapMixin

from .models import StockItem


class StockItemForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = StockItem
        fields = ["name", "area", "unit", "reorder_level", "unit_cost", "supplier", "is_active"]


class ReceiveForm(BootstrapMixin, forms.Form):
    quantity = forms.DecimalField(min_value=Decimal("0.01"), max_digits=12, decimal_places=2)
    unit_cost = forms.DecimalField(label="Cost per unit (KES)", min_value=Decimal("0"), max_digits=10, decimal_places=2)
    supplier = forms.CharField(max_length=120, required=False)
    reference = forms.CharField(max_length=60, required=False, label="Invoice / receipt no.")
    method = forms.ChoiceField(label="Paid by", choices=[("CASH", "Cash"), ("MPESA", "M-Pesa"), ("BANK", "Bank transfer"),
                                                         ("CREDIT", "On credit (unpaid)")])
    record_expense = forms.BooleanField(required=False, initial=True, label="Record the cost as an expense")


class AdjustForm(BootstrapMixin, forms.Form):
    action = forms.ChoiceField(choices=[("count", "Stock count (set the actual quantity)"),
                                        ("waste", "Waste / breakage (remove)"),
                                        ("use", "Used in kitchen / housekeeping (remove)")])
    quantity = forms.DecimalField(min_value=Decimal("0"), max_digits=12, decimal_places=2)
    note = forms.CharField(max_length=200, required=False)
