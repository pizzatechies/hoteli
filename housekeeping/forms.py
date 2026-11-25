from django import forms

from accounts.models import User
from core.forms import BootstrapMixin, DateInput

from .models import HousekeepingTask, MaintenanceRequest


def staff_choices(*roles):
    qs = User.objects.filter(is_active=True)
    if roles:
        qs = qs.filter(role__in=roles)
    return qs


class HousekeepingTaskForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = HousekeepingTask
        fields = ["room", "task_type", "priority", "assigned_to", "due_date", "notes"]
        widgets = {"due_date": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = staff_choices(User.Role.HOUSEKEEPING, User.Role.MANAGER)


class MaintenanceForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = MaintenanceRequest
        fields = ["room", "location", "title", "description", "priority", "puts_room_out_of_order",
                  "assigned_to", "status", "cost", "resolution_notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = staff_choices()
        if not self.instance.pk:
            self.fields.pop("status")
            self.fields.pop("resolution_notes")
            self.fields.pop("cost")

    def clean(self):
        data = super().clean()
        if not data.get("room") and not data.get("location"):
            self.add_error("location", "Choose a room or describe the location.")
        if data.get("puts_room_out_of_order") and not data.get("room"):
            self.add_error("puts_room_out_of_order", "Only a room can be taken out of order.")
        return data
