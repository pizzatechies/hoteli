from django.core.cache import cache
from django.db import models

CONTENT_CACHE_KEY = "website_content_v1"


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
