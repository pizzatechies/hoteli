from django.contrib import admin

from .models import C2BTransaction, MpesaCallbackLog, MpesaTransaction


@admin.register(MpesaTransaction)
class MpesaTransactionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "phone", "amount", "account_reference", "status", "mpesa_receipt", "is_simulated")
    list_filter = ("status", "is_simulated", "source")
    search_fields = ("phone", "mpesa_receipt", "checkout_request_id", "account_reference")


@admin.register(C2BTransaction)
class C2BTransactionAdmin(admin.ModelAdmin):
    list_display = ("trans_id", "trans_time", "amount", "bill_ref_number", "status")
    list_filter = ("status",)
    search_fields = ("trans_id", "bill_ref_number", "msisdn")


@admin.register(MpesaCallbackLog)
class MpesaCallbackLogAdmin(admin.ModelAdmin):
    list_display = ("received_at", "kind", "processed", "note")
    list_filter = ("kind", "processed")
