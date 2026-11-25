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
    path("p/<slug:slug>/", views.page_view, name="page"),
    path("staff/website/builder/", views.builder_index, name="builder"),
    path("staff/website/builder/pages/new/", views.builder_page_create, name="builder_page_create"),
    path("staff/website/builder/pages/<int:pk>/", views.builder_page, name="builder_page"),
    path("staff/website/builder/pages/<int:pk>/<str:action>/", views.builder_page_action, name="builder_page_action"),
    path("staff/website/builder/pages/<int:pk>/sections/add/", views.builder_section_add, name="builder_section_add"),
    path("staff/website/builder/sections/<int:pk>/", views.builder_section, name="builder_section"),
    path("staff/website/builder/sections/<int:pk>/<str:action>/", views.builder_section_action,
         name="builder_section_action"),
    path("staff/website/", views.manage, name="manage"),
    path("staff/website/facilities/new/", views.facility_form, name="facility_create"),
    path("staff/website/facilities/<int:pk>/", views.facility_form, name="facility_edit"),
    path("staff/inbox/", views.inbox, name="inbox"),
    path("staff/inbox/<int:pk>/toggle/", views.inbox_toggle, name="inbox_toggle"),
]
