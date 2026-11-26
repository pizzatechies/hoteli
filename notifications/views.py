from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts import permissions as P
from accounts.permissions import role_required
from bookings.models import Booking
from core.forms import BootstrapMixin
from core.models import log_action

from . import sms
from .models import SmsMessage


class SmsForm(BootstrapMixin, forms.Form):
    phone = forms.CharField(max_length=20)
    body = forms.CharField(widget=forms.Textarea(attrs={"rows": 3, "maxlength": 480}), label="Message",
                           max_length=480)


@role_required(*P.BOOKING_VIEW)
def message_list(request):
    qs = SmsMessage.objects.select_related("booking", "sent_by")
    status = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()
    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(Q(to__icontains=q) | Q(body__icontains=q) | Q(booking__reference__icontains=q))
    from django.conf import settings

    return render(request, "notifications/list.html", {
        "page": Paginator(qs, 30).get_page(request.GET.get("page")), "statuses": SmsMessage.Status.choices,
        "status": status, "q": q, "backend": settings.SMS_BACKEND,
        "form": SmsForm(),
    })


@role_required(*P.FRONT_DESK)
@require_POST
def send(request):
    form = SmsForm(request.POST)
    booking = None
    if request.POST.get("booking"):
        booking = get_object_or_404(Booking, pk=request.POST["booking"])
    if not form.is_valid():
        messages.error(request, "Enter a phone number and a message.")
    else:
        message = sms.queue_sms(form.cleaned_data["phone"], form.cleaned_data["body"], booking=booking,
                                user=request.user)
        if message is None:
            messages.error(request, "That phone number can't receive SMS. Use 07XX… or an international +… number.")
        else:
            log_action(request.user, "sms.send", message, f"SMS to {message.to}")
            messages.success(request, f"SMS queued to {message.to}.")
    if booking:
        return redirect("bookings:detail", pk=booking.pk)
    return redirect("notifications:list")


@role_required(*P.FRONT_DESK)
@require_POST
def retry(request, pk):
    message = get_object_or_404(SmsMessage, pk=pk)
    if message.status == SmsMessage.Status.FAILED:
        message.status = SmsMessage.Status.QUEUED
        message.attempts = 0
        message.save(update_fields=["status", "attempts"])
    sms.deliver(message)
    messages.info(request, f"Retried: {message.get_status_display()}.")
    return redirect("notifications:list")
