from django.conf import settings

from .models import HotelSettings


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
    from website.models import ContactMessage, WebsiteContent

    unread = 0
    if nav.get("front_desk"):
        unread = ContactMessage.objects.filter(is_read=False).count()
    return {
        "hotel": HotelSettings.load(),
        "site": WebsiteContent.load(),
        "unread_messages": unread,
        "mpesa_mode": mode_label(),
        "mpesa_simulated": settings.MPESA_SIMULATE,
        "nav": nav,
    }
