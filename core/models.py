import datetime
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

SETTINGS_CACHE_KEY = "hotel_settings_v1"
BRAND_CACHE_KEY = "hotel_brand_assets_v1"


class HotelSettings(models.Model):
    """Single-row table holding property-wide configuration."""

    name = models.CharField(max_length=120, default="Hoteli Grand")
    tagline = models.CharField(max_length=200, blank=True, default="Comfort, the Kenyan way")
    address = models.CharField(max_length=255, blank=True, default="Nairobi, Kenya")
    phone = models.CharField(max_length=40, blank=True, default="+254 700 000 000")
    email = models.EmailField(blank=True, default="reservations@hoteli.local")
    website = models.URLField(blank=True)
    legal_name = models.CharField(
        "Registered business name", max_length=150, blank=True,
        help_text="Shown on invoices and receipts if it differs from the hotel name, e.g. Grand Hospitality Ltd.",
    )
    kra_pin = models.CharField("KRA PIN", max_length=20, blank=True)
    currency = models.CharField(max_length=5, default="KES")

    check_in_time = models.TimeField(default=datetime.time(14, 0))
    check_out_time = models.TimeField(default=datetime.time(10, 0))

    # Prices in the system are tax inclusive; these rates are used to show the breakdown.
    vat_rate = models.DecimalField(
        "VAT %", max_digits=5, decimal_places=2, default=Decimal("16.00"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    catering_levy_rate = models.DecimalField(
        "Catering levy %", max_digits=5, decimal_places=2, default=Decimal("2.00"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    show_tax_breakdown = models.BooleanField(
        default=True, help_text="Show VAT and levy breakdown on invoices (prices are tax inclusive)."
    )

    website_booking_enabled = models.BooleanField(
        default=True, help_text="Allow guests to book online from the public website."
    )
    website_require_deposit = models.BooleanField(
        default=True,
        help_text="Online bookings stay pending until an M-Pesa deposit is paid.",
    )
    deposit_percent = models.PositiveIntegerField(
        default=50, validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text="Deposit required for online bookings, as a percentage of the stay total.",
    )
    pending_hold_minutes = models.PositiveIntegerField(
        default=30, validators=[MinValueValidator(5)],
        help_text="Unpaid online bookings are released after this many minutes.",
    )
    allow_checkout_with_balance = models.BooleanField(
        default=False,
        help_text="Let front desk check guests out with an unpaid balance (managers can always override).",
    )
    require_two_factor_for_managers = models.BooleanField(
        "Require two-step login for managers and admins", default=False,
        help_text="Managers and administrators must set up an authenticator app before using the system.",
    )
    require_guest_id_at_checkin = models.BooleanField(
        default=True, help_text="Require an ID/passport number before check-in."
    )
    logo_show_name = models.BooleanField(
        "Show hotel name beside the logo", default=True,
        help_text="Turn off if your logo already contains the hotel name.",
    )
    invoice_footer = models.TextField(
        blank=True, default="Thank you for staying with us. Karibu tena!"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "hotel settings"
        verbose_name_plural = "hotel settings"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(SETTINGS_CACHE_KEY)

    def delete(self, *args, **kwargs):  # pragma: no cover - singleton is never deleted
        pass

    @classmethod
    def load(cls):
        obj = cache.get(SETTINGS_CACHE_KEY)
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=1)
            cache.set(SETTINGS_CACHE_KEY, obj, 300)
        return obj

    @property
    def total_tax_rate(self):
        return self.vat_rate + self.catering_levy_rate

    def tax_breakdown(self, gross):
        """Split a tax-inclusive amount into net, VAT and levy."""
        gross = Decimal(gross)
        divisor = Decimal(1) + self.total_tax_rate / Decimal(100)
        net = (gross / divisor).quantize(Decimal("0.01"))
        vat = (net * self.vat_rate / Decimal(100)).quantize(Decimal("0.01"))
        levy = gross - net - vat
        return {"net": net, "vat": vat, "levy": levy, "gross": gross}


class BrandAsset(models.Model):
    """Logo files, stored in the database so they survive redeploys on hosts without persistent disks."""

    class Kind(models.TextChoices):
        LOGO = "logo", "Main logo"
        LOGO_LIGHT = "logo-light", "Logo for dark backgrounds"
        FAVICON = "favicon", "Browser tab icon (favicon)"

    kind = models.CharField(max_length=20, choices=Kind.choices, unique=True)
    filename = models.CharField(max_length=150, blank=True)
    content_type = models.CharField(max_length=40)
    data = models.BinaryField()
    size = models.PositiveIntegerField(default=0)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.get_kind_display()

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache.delete(BRAND_CACHE_KEY)

    def delete(self, *args, **kwargs):
        result = super().delete(*args, **kwargs)
        cache.delete(BRAND_CACHE_KEY)
        return result

    @property
    def url(self):
        from django.urls import reverse

        return f"{reverse('brand_asset_public', args=[self.kind])}?v={int(self.updated_at.timestamp())}"

    @classmethod
    def urls(cls):
        """{'logo': url, 'logo_light': url, 'favicon': url} for the assets that exist (cached)."""
        urls = cache.get(BRAND_CACHE_KEY)
        if urls is None:
            urls = {a.kind.replace("-", "_"): a.url for a in cls.objects.defer("data")}
            cache.set(BRAND_CACHE_KEY, urls, 300)
        return urls


class AuditLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_logs"
    )
    action = models.CharField(max_length=60)
    object_type = models.CharField(max_length=60, blank=True)
    object_id = models.CharField(max_length=40, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} {self.description}"


def log_action(user, action, obj=None, description=""):
    """Record an auditable event. ``user`` may be None for system/guest actions."""
    if user is not None and not getattr(user, "is_authenticated", False):
        user = None
    return AuditLog.objects.create(
        user=user,
        action=action,
        object_type=obj.__class__.__name__ if obj is not None else "",
        object_id=str(obj.pk) if obj is not None and obj.pk is not None else "",
        description=description or (str(obj) if obj is not None else ""),
    )


class DailyJobRun(models.Model):
    """Marks a once-a-day background job as done, so it runs once even with several workers."""

    name = models.CharField(max_length=60)
    run_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("name", "run_date")]
        ordering = ["-run_date", "name"]

    def __str__(self):
        return f"{self.name} {self.run_date}"
