from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.message_list, name="list"),
    path("send/", views.send, name="send"),
    path("<int:pk>/retry/", views.retry, name="retry"),
]
