from django import forms

from .models import HotelSettings


class BootstrapMixin:
    """Adds Bootstrap 5 classes to every widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput,)):
                css = "form-check-input"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css = "form-select"
            elif isinstance(widget, (forms.RadioSelect, forms.CheckboxSelectMultiple)):
                css = ""
            else:
                css = "form-control"
            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{existing} {css}".strip()
            if isinstance(widget, forms.Textarea) and "rows" not in widget.attrs:
                widget.attrs["rows"] = 3


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, attrs=None):
        super().__init__(attrs=attrs, format="%Y-%m-%d")


class TimeInput(forms.TimeInput):
    input_type = "time"

    def __init__(self, attrs=None):
        super().__init__(attrs=attrs, format="%H:%M")


class HotelSettingsForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = HotelSettings
        exclude = ["updated_at"]
        widgets = {
            "check_in_time": TimeInput(),
            "check_out_time": TimeInput(),
            "invoice_footer": forms.Textarea(attrs={"rows": 2}),
        }


class HotelIdentityForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = HotelSettings
        fields = ["name", "tagline", "legal_name", "logo_show_name"]
        labels = {"name": "Hotel name", "logo_show_name": "Show the hotel name next to the logo"}
        help_texts = {
            "name": "Used everywhere: website, browser tabs, staff area, emails, invoices and receipts.",
            "tagline": "Short line under the name on the website, e.g. Comfort, the Kenyan way.",
            "logo_show_name": "Turn off if your logo already includes the name.",
        }

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if len(name) < 2:
            raise forms.ValidationError("Enter the hotel's name.")
        return name


class LogoUploadForm(forms.Form):
    file = forms.FileField(widget=forms.ClearableFileInput(attrs={
        "class": "form-control", "accept": "image/png,image/jpeg,image/webp,image/gif,image/svg+xml,image/x-icon,.ico,.svg",
    }))


class DateRangeForm(BootstrapMixin, forms.Form):
    start = forms.DateField(widget=DateInput())
    end = forms.DateField(widget=DateInput())

    def clean(self):
        data = super().clean()
        start, end = data.get("start"), data.get("end")
        if start and end:
            if end < start:
                raise forms.ValidationError("End date must be after start date.")
            if (end - start).days > 366:
                raise forms.ValidationError("Choose a range of at most one year.")
        return data
