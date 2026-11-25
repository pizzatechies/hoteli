from decimal import Decimal, InvalidOperation

from django import template
from django.contrib.humanize.templatetags.humanize import intcomma

register = template.Library()

BADGES = {
    # bookings
    "PENDING": "warning", "CONFIRMED": "primary", "CHECKED_IN": "success", "CHECKED_OUT": "secondary",
    "CANCELLED": "danger", "NO_SHOW": "dark",
    # m-pesa
    "SUCCESS": "success", "FAILED": "danger", "TIMEOUT": "dark",
    "MATCHED": "success", "UNMATCHED": "danger", "ALLOCATED": "info", "IGNORED": "secondary",
    # housekeeping / rooms
    "CLEAN": "success", "INSPECTED": "info", "DIRTY": "danger", "CLEANING": "warning",
    "IN_PROGRESS": "info", "DONE": "success", "OPEN": "warning", "RESOLVED": "success",
    # pos
    "CHARGED": "info", "PAID": "success",
    # priorities
    "URGENT": "danger", "HIGH": "warning", "MEDIUM": "info", "NORMAL": "secondary", "LOW": "light",
    # payments
    "PAYMENT": "success", "REFUND": "danger",
}


@register.filter
def money(value, places=2):
    """1234.5 -> '1,234.50'"""
    if value in (None, ""):
        return "0.00" if places else "0"
    try:
        value = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    return intcomma(f"{value:.{int(places)}f}")


@register.filter
def kes(value):
    return f"KES {money(value)}"


HEX_RE = __import__("re").compile(r"^#[0-9a-fA-F]{6}$")


@register.filter
def hexcolor(value, fallback="#0f766e"):
    """Only ever emit a valid #rrggbb into CSS."""
    return value if isinstance(value, str) and HEX_RE.match(value) else fallback


@register.filter
def badge(status):
    return BADGES.get(str(status), "secondary")


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def negate(value):
    try:
        return -Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value


@register.inclusion_tag("partials/status_badge.html")
def status_badge(obj, field="status"):
    value = getattr(obj, field)
    display = getattr(obj, f"get_{field}_display")()
    return {"value": value, "display": display, "color": BADGES.get(str(value), "secondary")}
