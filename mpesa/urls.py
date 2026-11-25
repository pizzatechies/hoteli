from django.urls import path

from . import views

app_name = "mpesa"

# NB: Daraja rejects callback URLs containing words like "mpesa" or "safaricom",
# so the public callback paths deliberately avoid them.
urlpatterns = [
    path("payments/callbacks/stk/<str:token>/", views.stk_callback, name="stk_callback"),
    path("payments/callbacks/c2b/validate/<str:token>/", views.c2b_validation, name="c2b_validation"),
    path("payments/callbacks/c2b/confirm/<str:token>/", views.c2b_confirmation, name="c2b_confirmation"),
    path("pay/status/<uuid:uuid>/", views.transaction_status, name="status"),
    path("pay/simulate/<uuid:uuid>/", views.simulate, name="simulate"),
    path("staff/mpesa/", views.transaction_list, name="list"),
    path("staff/mpesa/stk/", views.stk_start, name="stk_start"),
    path("staff/mpesa/<int:pk>/", views.transaction_detail, name="detail"),
    path("staff/mpesa/paybill/", views.c2b_list, name="c2b_list"),
    path("staff/mpesa/paybill/<int:pk>/allocate/", views.c2b_allocate, name="c2b_allocate"),
    path("staff/mpesa/callbacks/", views.callback_logs, name="callback_logs"),
]
