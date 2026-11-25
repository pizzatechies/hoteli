from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("night-audit/", views.run_night_audit, name="night_audit"),
    path("reports/", views.report_view, name="reports"),
    path("reports/export/<str:kind>/", views.report_export, name="report_export"),
    path("settings/", views.settings_view, name="settings"),
    path("audit-log/", views.audit_log, name="audit_log"),
]
