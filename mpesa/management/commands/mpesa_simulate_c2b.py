from django.core.management.base import BaseCommand, CommandError

from mpesa.daraja import DarajaClient, DarajaError


class Command(BaseCommand):
    help = "Sandbox only: ask Safaricom to simulate a Paybill payment to your registered C2B URL."

    def add_arguments(self, parser):
        parser.add_argument("account", help="Account number, e.g. a booking reference")
        parser.add_argument("amount", type=int)
        parser.add_argument("--msisdn", default="254708374149", help="Sandbox test MSISDN")

    def handle(self, *args, **options):
        try:
            data = DarajaClient().simulate_c2b(
                amount=options["amount"], msisdn=options["msisdn"], bill_ref_number=options["account"]
            )
        except DarajaError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(str(data)))
