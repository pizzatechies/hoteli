from django.contrib import admin
from django.urls import include, path

from accounts.views import admin_login_redirect
from core import views as core_views

# The Django admin signs in through the staff login, so lockout and two-step login apply there too.
admin.site.login = admin_login_redirect

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("staff/", include("core.urls")),
    path("brand/<str:kind>/", core_views.brand_asset, name="brand_asset_public"),
    path("staff/", include("accounts.urls")),
    path("staff/", include("bookings.urls")),
    path("staff/rooms/", include("rooms.urls")),
    path("staff/housekeeping/", include("housekeeping.urls")),
    path("staff/pos/", include("pos.urls")),
    path("", include("mpesa.urls")),
    path("", include("website.urls")),
]

handler403 = "core.views.permission_denied"
handler404 = "core.views.page_not_found"
