import re

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils.text import slugify

CONTENT_CACHE_KEY = "website_content_v1"
HEX_COLOR = RegexValidator(r"^#[0-9a-fA-F]{6}$", "Use a hex colour such as #0f766e.")
SAFE_LINK = re.compile(r"^(/|#|https?://|mailto:|tel:)", re.IGNORECASE)

HEADING_FONTS = [
    ("Playfair Display", "Playfair Display (elegant serif)"),
    ("Lora", "Lora (classic serif)"),
    ("Merriweather", "Merriweather (sturdy serif)"),
    ("Montserrat", "Montserrat (modern sans)"),
    ("Poppins", "Poppins (friendly sans)"),
    ("Inter", "Inter (clean sans)"),
]


def validate_link(value):
    if value and not SAFE_LINK.match(value.strip()):
        raise ValidationError("Links must start with /, #, https://, mailto: or tel:.")


class WebsiteContent(models.Model):
    """Editable copy for the public website (single row)."""

    hero_title = models.CharField(max_length=120, default="Your home away from home")
    hero_subtitle = models.CharField(
        max_length=255, default="Comfortable rooms, great food and warm Kenyan hospitality. Book direct and pay with M-Pesa."
    )
    hero_image_url = models.URLField(
        blank=True,
        default="https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=1600&q=70",
    )
    about_title = models.CharField(max_length=120, default="About us")
    about_text = models.TextField(
        default=(
            "We are an independent hotel offering comfortable, secure accommodation for business and leisure "
            "travellers. Enjoy free Wi-Fi, a restaurant serving local and international dishes, secure parking "
            "and a friendly team available around the clock."
        )
    )
    map_embed_url = models.URLField(
        blank=True, help_text="Google Maps 'embed a map' src URL (optional)."
    )
    whatsapp_number = models.CharField(max_length=20, blank=True, help_text="e.g. 254712345678")
    facebook_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    show_dining_menu = models.BooleanField(default=True, help_text="Show the restaurant menu on the website.")
    # Theme
    primary_color = models.CharField(max_length=7, default="#0f766e", validators=[HEX_COLOR],
                                     help_text="Buttons, links and highlights.")
    accent_color = models.CharField(max_length=7, default="#d97706", validators=[HEX_COLOR],
                                    help_text="Small labels and secondary buttons.")
    dark_color = models.CharField(max_length=7, default="#0f172a", validators=[HEX_COLOR],
                                  help_text="Footer and dark sections.")
    heading_font = models.CharField(max_length=40, choices=HEADING_FONTS, default="Playfair Display")
    logo_url = models.URLField(blank=True, help_text="Optional logo image (replaces the icon next to the name).")
    footer_text = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "website content"
        verbose_name_plural = "website content"

    def __str__(self):
        return "Website content"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(CONTENT_CACHE_KEY)

    @classmethod
    def load(cls):
        obj = cache.get(CONTENT_CACHE_KEY)
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=1)
            cache.set(CONTENT_CACHE_KEY, obj, 300)
        return obj


class Facility(models.Model):
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=255, blank=True)
    icon = models.CharField(
        max_length=40, default="star", help_text="Bootstrap icon name, e.g. wifi, cup-hot, p-circle, water"
    )
    display_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["display_order", "name"]
        verbose_name_plural = "facilities"

    def __str__(self):
        return self.name


class ContactMessage(models.Model):
    name = models.CharField(max_length=120)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    subject = models.CharField(max_length=150)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subject} – {self.name}"


class Page(models.Model):
    """A page assembled from sections in the website builder."""

    title = models.CharField(max_length=120)
    slug = models.SlugField(max_length=80, unique=True, help_text="Web address: /p/<slug>/")
    meta_description = models.CharField(max_length=160, blank=True, help_text="Shown in Google results.")
    is_published = models.BooleanField(default=False)
    is_home = models.BooleanField("Use as homepage", default=False,
                                  help_text="Replace the built-in homepage with this page.")
    show_in_nav = models.BooleanField("Show in menu", default=True)
    nav_label = models.CharField(max_length=40, blank=True, help_text="Menu text (defaults to the title).")
    nav_order = models.PositiveSmallIntegerField(default=10)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nav_order", "title"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:70] or "page"
            slug, n = base, 2
            while Page.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)
        if self.is_home:
            Page.objects.exclude(pk=self.pk).filter(is_home=True).update(is_home=False)

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("website:home") if self.is_home else reverse("website:page", args=[self.slug])

    @property
    def menu_label(self):
        return self.nav_label or self.title


class Section(models.Model):
    class Kind(models.TextChoices):
        HERO = "HERO", "Hero banner (with booking search)"
        TEXT = "TEXT", "Text"
        IMAGE_TEXT = "IMAGE_TEXT", "Image + text"
        ROOMS = "ROOMS", "Rooms & rates"
        FACILITIES = "FACILITIES", "Facilities"
        MENU = "MENU", "Restaurant menu highlights"
        GALLERY = "GALLERY", "Photo gallery"
        FEATURES = "FEATURES", "Feature list (icons)"
        TESTIMONIALS = "TESTIMONIALS", "Guest reviews"
        FAQ = "FAQ", "Questions & answers"
        CTA = "CTA", "Call to action"
        MAP = "MAP", "Map"
        CONTACT = "CONTACT", "Contact form"

    class Background(models.TextChoices):
        WHITE = "white", "White"
        SOFT = "soft", "Soft tint"
        BRAND = "brand", "Brand colour"
        DARK = "dark", "Dark"

    # Which form fields each section type uses (drives the editor UI).
    FIELDS = {
        Kind.HERO: ["title", "subtitle", "image_url", "show_search", "button_text", "button_url"],
        Kind.TEXT: ["eyebrow", "title", "body", "align"],
        Kind.IMAGE_TEXT: ["eyebrow", "title", "body", "image_url", "image_right", "button_text", "button_url"],
        Kind.ROOMS: ["eyebrow", "title", "subtitle", "limit"],
        Kind.FACILITIES: ["eyebrow", "title", "subtitle", "limit"],
        Kind.MENU: ["eyebrow", "title", "subtitle", "limit", "button_text", "button_url"],
        Kind.GALLERY: ["eyebrow", "title", "items"],
        Kind.FEATURES: ["eyebrow", "title", "items"],
        Kind.TESTIMONIALS: ["eyebrow", "title", "items"],
        Kind.FAQ: ["eyebrow", "title", "items"],
        Kind.CTA: ["title", "subtitle", "button_text", "button_url", "image_url"],
        Kind.MAP: ["title", "body", "embed_url"],
        Kind.CONTACT: ["title", "subtitle"],
    }
    ITEM_HELP = {
        Kind.GALLERY: "One photo per line:  image URL | caption",
        Kind.FEATURES: "One per line:  icon | title | description   (icons from icons.getbootstrap.com, e.g. wifi)",
        Kind.TESTIMONIALS: "One per line:  quote | guest name | where from (only use genuine guest feedback)",
        Kind.FAQ: "One per line:  question | answer",
    }

    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="sections")
    kind = models.CharField(max_length=15, choices=Kind.choices)
    order = models.PositiveIntegerField(default=0)
    is_visible = models.BooleanField(default=True)
    background = models.CharField(max_length=6, choices=Background.choices, default=Background.WHITE)
    eyebrow = models.CharField("Small label", max_length=60, blank=True)
    title = models.CharField(max_length=150, blank=True)
    subtitle = models.CharField(max_length=255, blank=True)
    body = models.TextField(blank=True, help_text="Plain text. Blank lines start a new paragraph.")
    image_url = models.URLField(max_length=500, blank=True)
    image_right = models.BooleanField("Image on the right", default=False)
    align = models.CharField(max_length=6, choices=[("left", "Left"), ("center", "Centre")], default="left")
    button_text = models.CharField(max_length=40, blank=True)
    button_url = models.CharField(max_length=300, blank=True, validators=[validate_link],
                                  help_text="e.g. /book/, /contact/, https://wa.me/2547…")
    show_search = models.BooleanField("Show booking search", default=True)
    limit = models.PositiveSmallIntegerField("Items to show", default=6)
    items = models.TextField(blank=True)
    embed_url = models.URLField("Google Maps embed URL", max_length=600, blank=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.get_kind_display()} – {self.title or 'untitled'}"

    def clean(self):
        if self.embed_url and not self.embed_url.startswith("https://www.google.com/maps/embed"):
            raise ValidationError({"embed_url": "Paste the src link from Google Maps → Share → Embed a map."})

    @property
    def fields(self):
        return self.FIELDS.get(self.kind, [])

    def item_rows(self):
        """Parse the pipe-separated items text into lists of cells."""
        rows = []
        for line in self.items.splitlines():
            if line.strip():
                rows.append([cell.strip() for cell in line.split("|")])
        return rows

    def gallery(self):
        return [{"url": r[0], "caption": r[1] if len(r) > 1 else ""}
                for r in self.item_rows() if r[0].startswith("https://")]

    def features(self):
        return [{"icon": re.sub(r"[^a-z0-9-]", "", r[0].lower()) or "star", "title": r[1] if len(r) > 1 else "",
                 "text": r[2] if len(r) > 2 else ""} for r in self.item_rows()]

    def testimonials(self):
        return [{"quote": r[0], "name": r[1] if len(r) > 1 else "", "origin": r[2] if len(r) > 2 else ""}
                for r in self.item_rows()]

    def faqs(self):
        return [{"q": r[0], "a": " | ".join(r[1:])} for r in self.item_rows() if len(r) > 1]
