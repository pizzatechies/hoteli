from django import forms
from django.contrib.auth.forms import UserCreationForm

from core.forms import BootstrapMixin

from .models import User


class StaffCreateForm(BootstrapMixin, UserCreationForm):
    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "phone", "role"]


class StaffEditForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone", "role", "is_active"]


class PasswordResetByAdminForm(BootstrapMixin, forms.Form):
    new_password = forms.CharField(widget=forms.PasswordInput, min_length=8)
