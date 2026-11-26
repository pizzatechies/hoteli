"""Background worker: runs the hotel's scheduled jobs in a loop.

Used as the `jobs` container on AWS/Docker so no cron is needed:

    python manage.py run_jobs            # forever
    python manage.py run_jobs --once     # one pass (handy for testing)

Every job is idempotent, so running more than one worker is safe.
"""

import logging
import os
import time

from django.core.management.base import BaseCommand
from django.db import IntegrityError, close_old_connections
from django.utils import timezone

logger = logging.getLogger("bookings")


def _expire_holds():
    from bookings.services import expire_pending_holds

    return expire_pending_holds()


def _mpesa_pending():
    from django.core.management import call_command

    call_command("mpesa_check_pending", verbosity=0)


def _night_audit():
    from bookings.services import night_audit

    return night_audit()


INTERVAL_JOBS = [
    # name, every N seconds, function
    ("expire_holds", 300, _expire_holds),
    ("mpesa_check_pending", 120, _mpesa_pending),
]
DAILY_JOBS = [
    # name, local time (env override), function
    ("night_audit", os.environ.get("NIGHT_AUDIT_TIME", "23:30"), _night_audit),
]


def register_interval(name, seconds, func):
    if name not in {j[0] for j in INTERVAL_JOBS}:
        INTERVAL_JOBS.append((name, seconds, func))


def register_daily(name, at, func):
    if name not in {j[0] for j in DAILY_JOBS}:
        DAILY_JOBS.append((name, at, func))


def run_daily_once(name, func, today=None):
    """Run `func` if no worker has run job `name` today. Returns True if it ran."""
    from core.models import DailyJobRun

    today = today or timezone.localdate()
    try:
        DailyJobRun.objects.create(name=name, run_date=today)
    except IntegrityError:
        return False
    func()
    return True


class Command(BaseCommand):
    help = "Run scheduled jobs (hold expiry, M-Pesa status checks, night audit, reports…) in a loop."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run every due job once and exit.")
        parser.add_argument("--sleep", type=int, default=30)

    def handle(self, *args, **opts):
        from core import jobs  # noqa: F401  (registers jobs contributed by other features)

        last_run = {}
        self.stdout.write("Hoteli job runner started.")
        while True:
            close_old_connections()
            now = time.monotonic()
            for name, every, func in INTERVAL_JOBS:
                if opts["once"] or now - last_run.get(name, -every) >= every:
                    last_run[name] = now
                    self._safe(name, func)
            local = timezone.localtime()
            for name, at, func in DAILY_JOBS:
                hour, minute = (int(x) for x in at.split(":"))
                if opts["once"] or (local.hour, local.minute) >= (hour, minute):
                    self._safe(name, lambda n=name, f=func: run_daily_once(n, f))
            if opts["once"]:
                return
            time.sleep(opts["sleep"])

    def _safe(self, name, func):
        try:
            func()
        except Exception:  # noqa: BLE001 - one failing job must not stop the others
            logger.exception("Background job %s failed", name)
            close_old_connections()

