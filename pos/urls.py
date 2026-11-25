from django.urls import path

from . import views

app_name = "pos"

urlpatterns = [
    path("", views.home, name="home"),
    path("orders/", views.order_list, name="orders"),
    path("orders/new/", views.order_create, name="order_create"),
    path("orders/<int:pk>/", views.order_detail, name="order"),
    path("orders/<int:pk>/items/add/", views.order_add_item, name="order_add_item"),
    path("orders/<int:pk>/items/<int:item_id>/", views.order_update_item, name="order_update_item"),
    path("orders/<int:pk>/charge-room/", views.order_charge_room, name="order_charge_room"),
    path("orders/<int:pk>/pay/", views.order_pay, name="order_pay"),
    path("orders/<int:pk>/cancel/", views.order_cancel, name="order_cancel"),
    path("orders/<int:pk>/bill/", views.order_bill, name="order_bill"),
    path("menu/", views.menu, name="menu"),
    path("menu/items/new/", views.menu_item_form, name="item_create"),
    path("menu/items/<int:pk>/edit/", views.menu_item_form, name="item_edit"),
    path("menu/categories/new/", views.menu_category_form, name="category_create"),
    path("menu/categories/<int:pk>/edit/", views.menu_category_form, name="category_edit"),
]
