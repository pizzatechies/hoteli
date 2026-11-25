from django.core.management.base import BaseCommand

from bookings.services import expire_pending_holds


class Command(BaseCommand):
    help = "Release unpaid online bookings whose hold time has passed."

    def handle(self, *args, **options):
        count = expire_pending_holds()
        self.stdout.write(self.style.SUCCESS(f"Released {count} expired hold(s)."))
