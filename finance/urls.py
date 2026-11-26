from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("expenses/", views.expense_list, name="expenses"),
    path("expenses/new/", views.expense_form, name="expense_create"),
    path("expenses/<int:pk>/", views.expense_form, name="expense_edit"),
    path("profit-and-loss/", views.profit_loss, name="profit_loss"),
]
