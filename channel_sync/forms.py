from django import forms

from core.forms import BootstrapMixin, DateInput

from .models import ChannelCalendar, RoomBlock


class ChannelCalendarForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = ChannelCalendar
        fields = ["room", "name", "import_url", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["room"].label_from_instance = lambda r: f"{r.number} – {r.room_type.name}"

    def clean_import_url(self):
        url = self.cleaned_data.get("import_url", "").strip()
        if url and not url.lower().startswith("https://"):
            raise forms.ValidationError("Use the https:// calendar (iCal) link from the other site.")
        return url


class RoomBlockForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = RoomBlock
        fields = ["room", "start_date", "end_date", "summary"]
        widgets = {"start_date": DateInput(), "end_date": DateInput()}
        labels = {"start_date": "From", "end_date": "Until (free again on)", "summary": "Reason"}

    def clean(self):
        data = super().clean()
        if data.get("start_date") and data.get("end_date") and data["end_date"] <= data["start_date"]:
            self.add_error("end_date", "Must be after the start date.")
        return data
