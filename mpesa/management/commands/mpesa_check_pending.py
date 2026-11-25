import datetime

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from mpesa.models import MpesaTransaction
from mpesa.services import refresh_transaction_status


class Command(BaseCommand):
    help = "Ask Daraja for the status of STK pushes that are still pending (missed callbacks)."

    def handle(self, *args, **options):
        cutoff = timezone.now() - datetime.timedelta(seconds=settings.MPESA_QUERY_AFTER_SECONDS)
        pending = MpesaTransaction.objects.filter(
            status=MpesaTransaction.Status.PENDING, is_simulated=False, created_at__lte=cutoff,
            created_at__gte=timezone.now() - datetime.timedelta(days=2),
        )
        changed = 0
        for tx in pending:
            before = tx.status
            tx = refresh_transaction_status(tx, force=True)
            if tx.status != before:
                changed += 1
                self.stdout.write(f"{tx.checkout_request_id}: {before} -> {tx.status}")
        self.stdout.write(self.style.SUCCESS(f"Checked {pending.count()} pending transaction(s); {changed} updated."))
