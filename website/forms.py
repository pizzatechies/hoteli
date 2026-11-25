from django import forms

from core.forms import BootstrapMixin, DateInput

from .models import ContactMessage, Facility, Page, Section, WebsiteContent


class SearchForm(BootstrapMixin, forms.Form):
    check_in = forms.DateField(widget=DateInput(), label="Check-in")
    check_out = forms.DateField(widget=DateInput(), label="Check-out")
    adults = forms.IntegerField(min_value=1, max_value=10, initial=2)
    children = forms.IntegerField(min_value=0, max_value=10, initial=0)

    def __init__(self, *args, today=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.today = today

    def clean(self):
        data = super().clean()
        ci, co = data.get("check_in"), data.get("check_out")
        if ci and self.today and ci < self.today:
            self.add_error("check_in", "Check-in cannot be in the past.")
        if ci and co:
            if co <= ci:
                self.add_error("check_out", "Check-out must be after check-in.")
            elif (co - ci).days > 30:
                self.add_error("check_out", "For stays longer than 30 nights please contact us directly.")
        if ci and self.today and (ci - self.today).days > 365:
            self.add_error("check_in", "We take online bookings up to a year ahead.")
        return data


class GuestDetailsForm(BootstrapMixin, forms.Form):
    first_name = forms.CharField(max_length=60)
    last_name = forms.CharField(max_length=60)
    phone = forms.CharField(max_length=20, label="M-Pesa / mobile number", help_text="e.g. 0712 345 678")
    email = forms.EmailField(help_text="We'll send your confirmation here.")
    special_requests = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False,
                                       label="Special requests (optional)")
    accept_terms = forms.BooleanField(label="I agree to the booking and cancellation policy")
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"autocomplete": "off", "tabindex": "-1"}))

    def clean_phone(self):
        from mpesa.utils import normalize_phone

        phone = self.cleaned_data["phone"]
        try:
            normalize_phone(phone)
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc
        return phone.strip()

    def clean_website(self):  # honeypot
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("Spam detected.")
        return ""


class LookupForm(BootstrapMixin, forms.Form):
    reference = forms.CharField(max_length=12, label="Booking reference", help_text="e.g. HB7K2M9Q")
    contact = forms.CharField(max_length=120, label="Phone number or email used to book")


class PayForm(BootstrapMixin, forms.Form):
    phone = forms.CharField(max_length=20, label="M-Pesa number")
    amount = forms.IntegerField(min_value=1, max_value=250000)


class ContactForm(BootstrapMixin, forms.ModelForm):
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"autocomplete": "off", "tabindex": "-1"}))

    class Meta:
        model = ContactMessage
        fields = ["name", "email", "phone", "subject", "message"]
        widgets = {"message": forms.Textarea(attrs={"rows": 5})}

    def clean(self):
        data = super().clean()
        if data.get("website"):
            raise forms.ValidationError("Spam detected.")
        if not data.get("email") and not data.get("phone"):
            raise forms.ValidationError("Give us an email or phone number so we can reply.")
        return data


THEME_FIELDS = ["primary_color", "accent_color", "dark_color", "heading_font", "footer_text"]


class WebsiteContentForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = WebsiteContent
        exclude = ["updated_at", *THEME_FIELDS]
        widgets = {"about_text": forms.Textarea(attrs={"rows": 5})}


class ColorInput(forms.TextInput):
    input_type = "color"


class ThemeForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = WebsiteContent
        fields = THEME_FIELDS
        labels = {"primary_color": "Primary", "accent_color": "Accent", "dark_color": "Dark"}
        widgets = {"primary_color": ColorInput(attrs={"class": "form-control-color"}),
                   "accent_color": ColorInput(attrs={"class": "form-control-color"}),
                   "dark_color": ColorInput(attrs={"class": "form-control-color"})}


class PageForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Page
        fields = ["title", "slug", "meta_description", "is_published", "is_home", "show_in_nav", "nav_label",
                  "nav_order"]
        labels = {"is_published": "Published (visible to guests)", "nav_label": "Menu label",
                  "nav_order": "Menu position", "slug": "Web address"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        self.fields["slug"].help_text = "Leave blank to create it from the title."


class NewPageForm(BootstrapMixin, forms.Form):
    title = forms.CharField(max_length=120)
    template = forms.ChoiceField(choices=[])

    def __init__(self, *args, **kwargs):
        from .builder import PAGE_TEMPLATES

        super().__init__(*args, **kwargs)
        self.fields["template"].choices = [(k, v["label"]) for k, v in PAGE_TEMPLATES.items()]
        self.fields["template"].label = "Start from"


class SectionForm(BootstrapMixin, forms.ModelForm):
    COMMON = ["background", "is_visible"]

    class Meta:
        model = Section
        fields = ["eyebrow", "title", "subtitle", "body", "image_url", "image_right", "align", "show_search",
                  "button_text", "button_url", "limit", "items", "embed_url", "background", "is_visible"]
        widgets = {"body": forms.Textarea(attrs={"rows": 6}), "items": forms.Textarea(attrs={"rows": 6})}
        labels = {"image_url": "Image URL", "button_url": "Button link", "embed_url": "Google Maps embed URL"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        keep = set(self.instance.fields) | set(self.COMMON)
        for name in list(self.fields):
            if name not in keep:
                del self.fields[name]
        if "items" in self.fields:
            self.fields["items"].help_text = Section.ITEM_HELP.get(self.instance.kind, "")
            self.fields["items"].label = "Items"
        if "limit" in self.fields:
            self.fields["limit"].widget.attrs["max"] = 24
        if "is_visible" in self.fields:
            self.fields["is_visible"].label = "Visible on the website"


class FacilityForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Facility
        fields = ["name", "description", "icon", "display_order", "is_active"]
