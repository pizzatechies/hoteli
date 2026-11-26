from django import forms

from core.forms import BootstrapMixin, DateInput

from .models import Expense


class ExpenseForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["date", "category", "description", "amount", "method", "supplier", "reference"]
        widgets = {"date": DateInput()}
