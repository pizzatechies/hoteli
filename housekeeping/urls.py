from django.urls import path

from . import views

app_name = "housekeeping"

urlpatterns = [
    path("", views.board, name="board"),
    path("rooms/<int:pk>/status/", views.room_status, name="room_status"),
    path("tasks/", views.task_list, name="tasks"),
    path("tasks/new/", views.task_form, name="task_create"),
    path("tasks/<int:pk>/edit/", views.task_form, name="task_edit"),
    path("tasks/<int:pk>/<str:action>/", views.task_action, name="task_action"),
    path("maintenance/", views.maintenance_list, name="maintenance"),
    path("maintenance/new/", views.maintenance_form, name="maintenance_create"),
    path("maintenance/<int:pk>/", views.maintenance_form, name="maintenance_edit"),
]
