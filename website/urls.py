from django.urls import path

from . import views

app_name = "website"

urlpatterns = [
    path("", views.home, name="home"),
    path("rooms/", views.rooms, name="rooms"),
    path("rooms/<int:pk>/", views.room_detail, name="room_detail"),
    path("dining/", views.dining, name="dining"),
    path("facilities/", views.facilities, name="facilities"),
    path("contact/", views.contact, name="contact"),
    path("book/", views.search, name="search"),
    path("book/<int:pk>/", views.book, name="book"),
    path("booking/find/", views.lookup, name="lookup"),
    path("booking/<uuid:token>/", views.booking_page, name="booking"),
    path("booking/<uuid:token>/pay/", views.booking_pay, name="booking_pay"),
    path("staff/website/", views.manage, name="manage"),
    path("staff/website/facilities/new/", views.facility_form, name="facility_create"),
    path("staff/website/facilities/<int:pk>/", views.facility_form, name="facility_edit"),
    path("staff/inbox/", views.inbox, name="inbox"),
    path("staff/inbox/<int:pk>/toggle/", views.inbox_toggle, name="inbox_toggle"),
]
