from django.urls import path

from . import views

app_name = "bookings"

urlpatterns = [
    path("frontdesk/", views.front_desk, name="front_desk"),
    path("frontdesk/guest-register/", views.guest_register, name="guest_register"),
    path("calendar/", views.tape_chart, name="tape_chart"),
    path("bookings/", views.booking_list, name="list"),
    path("bookings/new/", views.booking_create, name="create"),
    path("bookings/availability/", views.availability_json, name="availability"),
    path("bookings/<int:pk>/", views.booking_detail, name="detail"),
    path("bookings/<int:pk>/edit/", views.booking_edit, name="edit"),
    path("bookings/<int:pk>/check-in/", views.booking_check_in, name="check_in"),
    path("bookings/<int:pk>/check-out/", views.booking_check_out, name="check_out"),
    path("bookings/<int:pk>/cancel/", views.booking_cancel, name="cancel"),
    path("bookings/<int:pk>/no-show/", views.booking_no_show, name="no_show"),
    path("bookings/<int:pk>/confirm/", views.booking_confirm, name="confirm"),
    path("bookings/<int:pk>/resend-confirmation/", views.booking_resend_confirmation, name="resend_confirmation"),
    path("bookings/<int:pk>/charges/add/", views.charge_add, name="charge_add"),
    path("bookings/<int:pk>/charges/<int:charge_id>/void/", views.charge_void, name="charge_void"),
    path("bookings/<int:pk>/payments/add/", views.payment_add, name="payment_add"),
    path("bookings/<int:pk>/payments/refund/", views.payment_refund, name="payment_refund"),
    path("bookings/<int:pk>/invoice/", views.invoice, name="invoice"),
    path("payments/", views.payment_list, name="payment_list"),
    path("payments/<int:payment_id>/receipt/", views.receipt, name="receipt"),
    path("payments/<int:payment_id>/void/", views.payment_void, name="payment_void"),
    path("guests/", views.guest_list, name="guest_list"),
    path("guests/new/", views.guest_create, name="guest_create"),
    path("guests/search/", views.guest_search, name="guest_search"),
    path("guests/<int:pk>/", views.guest_detail, name="guest_detail"),
    path("guests/<int:pk>/edit/", views.guest_edit, name="guest_edit"),
]
