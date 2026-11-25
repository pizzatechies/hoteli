from django.conf import settings

from .models import BrandAsset, HotelSettings


def hotel(request):
    from mpesa.services import mode_label

    user = getattr(request, "user", None)
    nav = {}
    if user is not None and user.is_authenticated:
        from accounts import permissions as P

        nav = {
            "front_desk": user.has_role(*P.FRONT_DESK),
            "bookings": user.has_role(*P.BOOKING_VIEW),
            "finance": user.has_role(*P.FINANCE),
            "housekeeping": user.has_role(*P.HOUSEKEEPING),
            "pos": user.has_role(*P.POS),
            "reports": user.has_role(*P.REPORTS),
            "management": user.has_role(*P.MANAGEMENT),
            "admin": user.is_admin,
        }
    from website.models import ContactMessage, Page, WebsiteContent

    unread = 0
    if nav.get("front_desk"):
        unread = ContactMessage.objects.filter(is_read=False).count()
    return {
        "hotel": HotelSettings.load(),
        "brand": BrandAsset.urls(),
        "site": WebsiteContent.load(),
        "unread_messages": unread,
        "nav_pages": [] if request.path.startswith("/staff/") else list(
            Page.objects.filter(is_published=True, show_in_nav=True, is_home=False).only(
                "title", "slug", "nav_label", "nav_order", "is_home")
        ),
        "mpesa_mode": mode_label(),
        "mpesa_simulated": settings.MPESA_SIMULATE,
        "nav": nav,
    }
