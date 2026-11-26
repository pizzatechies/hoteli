from django.urls import path

from . import views

app_name = "rooms"

urlpatterns = [
    path("", views.room_list, name="list"),
    path("new/", views.room_form, name="create"),
    path("<int:pk>/edit/", views.room_form, name="edit"),
    path("types/", views.room_type_list, name="types"),
    path("types/new/", views.room_type_form, name="type_create"),
    path("types/<int:pk>/edit/", views.room_type_form, name="type_edit"),
    path("rates/new/", views.season_form, name="season_create"),
    path("rates/<int:pk>/edit/", views.season_form, name="season_edit"),
    path("promos/new/", views.promo_form, name="promo_create"),
    path("promos/<int:pk>/", views.promo_form, name="promo_edit"),
    path("long-stay/new/", views.stay_discount_form, name="stay_discount_create"),
    path("long-stay/<int:pk>/", views.stay_discount_form, name="stay_discount_edit"),
    path("companies/new/", views.company_form, name="company_create"),
    path("companies/<int:pk>/", views.company_form, name="company_edit"),
]
