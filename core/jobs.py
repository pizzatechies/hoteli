"""Extra scheduled jobs contributed by features (imported by `run_jobs`)."""

from core.management.commands.run_jobs import register_interval


def _retry_sms():
    from notifications.sms import retry_queued

    retry_queued()


register_interval("sms_retry", 120, _retry_sms)
