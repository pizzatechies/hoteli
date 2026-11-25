from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_date

from bookings.services import night_audit


class Command(BaseCommand):
    help = "Post tonight's room charges for in-house guests, mark no-shows and release expired online holds."

    def add_arguments(self, parser):
        parser.add_argument("--date", help="Business date (YYYY-MM-DD). Defaults to today.")

    def handle(self, *args, **options):
        business_date = parse_date(options["date"]) if options.get("date") else None
        run = night_audit(business_date)
        self.stdout.write(self.style.SUCCESS(
            f"Night audit {run.business_date}: {run.room_charges_posted} room charges, "
            f"{run.no_shows} no-shows, {run.expired_holds} expired holds (cumulative for the day)."
        ))
