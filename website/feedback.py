import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger("bookings")


def request_feedback(booking):
    """Create a feedback link for a departed guest and send it by SMS and email (once)."""
    from core.models import HotelSettings
    from notifications import sms
    from notifications.models import SmsMessage

    from .models import GuestFeedback

    hotel = HotelSettings.load()
    if not hotel.feedback_requests:
        return None
    feedback, created = GuestFeedback.objects.get_or_create(booking=booking)
    if not created:
        return feedback
    link = f"{settings.SITE_URL}/feedback/{feedback.token}/"
    guest = booking.guest
    sms.queue_sms(guest.phone, f"Asante for staying at {hotel.name}, {guest.first_name}! How was it? "
                               f"Rate your stay in 10 seconds: {link}", kind=SmsMessage.Kind.FEEDBACK, booking=booking)
    if guest.email:
        try:
            send_mail(
                f"How was your stay at {hotel.name}?",
                f"Dear {guest.first_name},\n\nThank you for staying with us. We'd love to hear how it went – "
                f"it takes 10 seconds:\n\n{link}\n\n{hotel.name}",
                None, [guest.email], fail_silently=False,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Feedback email failed for %s", booking.reference)
    return feedback


def published_reviews(limit=6):
    from .models import GuestFeedback

    return list(GuestFeedback.objects.filter(is_published=True, rating__gte=4).exclude(comment="")
                .select_related("booking__guest")[:limit])
