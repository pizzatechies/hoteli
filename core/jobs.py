"""Extra scheduled jobs contributed by features (imported by `run_jobs`)."""

import os

from core.management.commands.run_jobs import register_daily, register_interval


def _retry_sms():
    from notifications.sms import retry_queued

    retry_queued()


register_interval("sms_retry", 120, _retry_sms)


def _sync_calendars():
    from channel_sync.services import sync_all

    sync_all()


register_interval("calendar_sync", 1800, _sync_calendars)


def _daily_report():
    from finance.daily import send_daily_report

    send_daily_report()


register_daily("daily_report", os.environ.get("DAILY_REPORT_TIME", "07:00"), _daily_report)
