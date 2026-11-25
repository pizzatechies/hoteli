from django.core.management.base import BaseCommand, CommandError

from mpesa.daraja import DarajaClient, DarajaError
from mpesa.services import c2b_urls, is_simulation


class Command(BaseCommand):
    help = "Register the Paybill (C2B) confirmation and validation URLs with Safaricom."

    def add_arguments(self, parser):
        parser.add_argument("--response-type", default="Completed", choices=["Completed", "Cancelled"],
                            help="What Safaricom does if the validation URL is unreachable.")

    def handle(self, *args, **options):
        if is_simulation():
            raise CommandError("M-Pesa is in simulation mode. Configure Daraja credentials first.")
        urls = c2b_urls()
        if not urls["confirmation"].startswith("https://"):
            raise CommandError(f"Callback URLs must be public HTTPS. Got {urls['confirmation']}")
        try:
            data = DarajaClient().register_c2b_urls(
                confirmation_url=urls["confirmation"], validation_url=urls["validation"],
                response_type=options["response_type"],
            )
        except DarajaError as exc:
            raise CommandError(f"Registration failed: {exc} {exc.response or ''}") from exc
        self.stdout.write(self.style.SUCCESS(f"Registered: {data}"))
        self.stdout.write(f"Confirmation: {urls['confirmation']}\nValidation:   {urls['validation']}")
