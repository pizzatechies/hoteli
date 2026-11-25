from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from mpesa.daraja import DarajaClient, DarajaError
from mpesa.services import is_simulation, stk_callback_url


class Command(BaseCommand):
    help = "Check M-Pesa configuration and Daraja credentials (gets an OAuth token)."

    def handle(self, *args, **options):
        self.stdout.write(f"Mode:          {'SIMULATION' if is_simulation() else settings.MPESA_ENVIRONMENT}")
        self.stdout.write(f"Shortcode:     {settings.MPESA_SHORTCODE} ({settings.MPESA_TRANSACTION_TYPE})")
        self.stdout.write(f"STK callback:  {stk_callback_url()}")
        if is_simulation():
            self.stdout.write(self.style.WARNING("Simulation mode – no call made to Safaricom."))
            return
        try:
            token = DarajaClient().get_access_token(force_refresh=True)
        except DarajaError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"OAuth OK (token {token[:6]}…). Credentials are valid."))
        if not stk_callback_url().startswith("https://"):
            self.stdout.write(self.style.WARNING("Callback URL is not HTTPS – Safaricom will not reach it."))
