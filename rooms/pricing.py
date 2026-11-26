"""Stay pricing: seasonal rates plus the single best discount (promo code, corporate rate or long stay)."""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q
from django.utils import timezone

from .models import CorporateAccount, PromoCode, StayDiscount

ZERO = Decimal("0.00")


@dataclass
class Quote:
    room_type: object
    check_in: object
    check_out: object
    base_total: Decimal
    discount_total: Decimal = ZERO
    discount_label: str = ""
    promo: PromoCode | None = None
    corporate: CorporateAccount | None = None
    promo_error: str = ""
    candidates: list = field(default_factory=list)

    @property
    def nights(self):
        return (self.check_out - self.check_in).days

    @property
    def total(self):
        return max(self.base_total - self.discount_total, ZERO)

    @property
    def nightly(self):
        return (self.total / self.nights).quantize(Decimal("0.01")) if self.nights else self.total

    @property
    def base_nightly(self):
        return (self.base_total / self.nights).quantize(Decimal("0.01")) if self.nights else self.base_total


def _money(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def find_promo(code, room_type, check_in, check_out, *, website=False):
    """Return (promo, error_message). error_message is '' when the code applies."""
    code = (code or "").strip().upper().replace(" ", "")
    if not code:
        return None, ""
    promo = PromoCode.objects.filter(code=code, is_active=True).prefetch_related("room_types").first()
    if promo is None or (website and not promo.on_website):
        return None, "That promo code isn't valid."
    nights = (check_out - check_in).days
    if promo.valid_from and check_in < promo.valid_from:
        return None, f"{promo.code} is valid for check-ins from {promo.valid_from:%d %b %Y}."
    if promo.valid_until and check_in > promo.valid_until:
        return None, f"{promo.code} has expired."
    if nights < promo.min_nights:
        return None, f"{promo.code} needs a stay of at least {promo.min_nights} nights."
    allowed = list(promo.room_types.all())
    if allowed and room_type not in allowed:
        return None, f"{promo.code} isn't valid for {room_type.name}."
    if promo.max_uses is not None and promo.times_used >= promo.max_uses:
        return None, f"{promo.code} has been fully used."
    return promo, ""


def quote(room_type, check_in, check_out, *, promo_code="", corporate=None, website=False):
    base = _money(room_type.quote(check_in, check_out))
    q = Quote(room_type=room_type, check_in=check_in, check_out=check_out, base_total=base)
    nights = q.nights
    promo, q.promo_error = find_promo(promo_code, room_type, check_in, check_out, website=website)
    if promo:
        amount = base * promo.percent_off / 100 if promo.percent_off else min(promo.amount_off, base)
        q.candidates.append((_money(amount), f"Promo {promo.code} ({promo.summary})", promo, None))
    if corporate and corporate.is_active and corporate.percent_off:
        q.candidates.append((_money(base * corporate.percent_off / 100),
                             f"{corporate.name} corporate rate ({corporate.percent_off:g}% off)", None, corporate))
    elif corporate and corporate.is_active:
        q.corporate = corporate
    stay = (StayDiscount.objects.filter(is_active=True, min_nights__lte=nights)
            .filter(Q(room_type=room_type) | Q(room_type__isnull=True))
            .order_by("-percent_off").first())
    if stay:
        q.candidates.append((_money(base * stay.percent_off / 100),
                             f"Long-stay discount ({stay.min_nights}+ nights, {stay.percent_off:g}% off)", None, None))
    if q.candidates:
        amount, label, best_promo, best_corporate = max(q.candidates, key=lambda c: c[0])
        q.discount_total, q.discount_label = amount, label
        q.promo = best_promo
        q.corporate = best_corporate or (corporate if corporate and corporate.is_active else None)
    return q


def use_promo(promo):
    """Count a use, refusing if the code ran out in the meantime. Call inside a transaction."""
    from django.db.models import F

    from bookings.services import BookingError

    locked = PromoCode.objects.select_for_update().get(pk=promo.pk)
    if locked.max_uses is not None and locked.times_used >= locked.max_uses:
        raise BookingError(f"{locked.code} has just been fully used.")
    PromoCode.objects.filter(pk=promo.pk).update(times_used=F("times_used") + 1)


def today():
    return timezone.localdate()
