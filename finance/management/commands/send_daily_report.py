from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_date

from finance.daily import recipients, send_daily_report


class Command(BaseCommand):
    help = "Email the daily summary (yesterday by default) to managers and the report addresses in Settings."

    def add_arguments(self, parser):
        parser.add_argument("--date", help="Day to report on (YYYY-MM-DD). Defaults to yesterday.")

    def handle(self, *args, **opts):
        day = parse_date(opts["date"]) if opts.get("date") else None
        sent = send_daily_report(day)
        if sent:
            self.stdout.write(self.style.SUCCESS(f"Sent to {sent} recipient(s): {', '.join(recipients())}"))
        else:
            self.stdout.write(self.style.WARNING("Nothing sent: add manager email addresses or report emails in Settings."))
