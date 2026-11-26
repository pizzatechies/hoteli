from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.stock_list, name="list"),
    path("new/", views.item_form, name="create"),
    path("<int:pk>/", views.item_detail, name="detail"),
    path("<int:pk>/edit/", views.item_form, name="edit"),
    path("<int:pk>/receive/", views.receive, name="receive"),
    path("<int:pk>/adjust/", views.adjust, name="adjust"),
]
