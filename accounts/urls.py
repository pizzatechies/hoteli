from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("login/verify/", views.login_verify, name="login_verify"),
    path("security/", views.account_security, name="security"),
    path("users/<int:pk>/reset-two-factor/", views.user_reset_two_factor, name="user_reset_two_factor"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("password/", views.PasswordChangeView.as_view(), name="password_change"),
    path("users/", views.user_list, name="users"),
    path("users/new/", views.user_create, name="user_create"),
    path("users/<int:pk>/", views.user_edit, name="user_edit"),
]
