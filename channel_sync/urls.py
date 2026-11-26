from django.urls import path

from . import views

app_name = "channel_sync"

urlpatterns = [
    path("ical/<uuid:token>.ics", views.feed, name="feed"),
    path("staff/channels/", views.channel_list, name="list"),
    path("staff/channels/new/", views.calendar_form, name="create"),
    path("staff/channels/<int:pk>/", views.calendar_form, name="edit"),
    path("staff/channels/sync/", views.sync_now, name="sync_all"),
    path("staff/channels/<int:pk>/sync/", views.sync_now, name="sync"),
    path("staff/channels/blocks/new/", views.block_create, name="block_create"),
    path("staff/channels/blocks/<int:pk>/delete/", views.block_delete, name="block_delete"),
]
