from django.contrib import admin

from .models import HousekeepingTask, MaintenanceRequest

admin.site.register(HousekeepingTask)
admin.site.register(MaintenanceRequest)
