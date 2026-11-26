"""Account security: authenticator-app codes (RFC 6238 TOTP), recovery codes and login lockout."""

import base64
import datetime
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from django.conf import settings
from django.utils import timezone

STEP_SECONDS = 30
DIGITS = 6
RECOVERY_CODES = 8


# ------------------------------------------------------------------------------ TOTP
def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret):
    padded = secret.upper() + "=" * (-len(secret) % 8)
    return base64.b32decode(padded)


def totp(secret, step):
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return f"{code:0{DIGITS}d}"


def current_step(now=None):
    return int((now if now is not None else time.time()) // STEP_SECONDS)


def verify_code(device, code, now=None):
    """Check a 6-digit code (±1 step for clock drift). Each code works only once."""
    code = "".join(ch for ch in str(code) if ch.isdigit())
    if len(code) != DIGITS:
        return False
    step = current_step(now)
    for candidate in (step - 1, step, step + 1):
        if candidate > device.last_used_step and hmac.compare_digest(totp(device.secret, candidate), code):
            device.last_used_step = candidate
            device.save(update_fields=["last_used_step"])
            return True
    return False


def provisioning_uri(device, issuer):
    label = quote(f"{issuer}:{device.user.username}")
    return (f"otpauth://totp/{label}?secret={device.secret}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}")


def _hash(code):
    return hashlib.sha256(code.replace("-", "").upper().encode()).hexdigest()


def make_recovery_codes(device):
    codes = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}".upper() for _ in range(RECOVERY_CODES)]
    device.recovery_codes = [_hash(c) for c in codes]
    device.save(update_fields=["recovery_codes"])
    return codes


def use_recovery_code(device, code):
    hashed = _hash(code.strip())
    if hashed in device.recovery_codes:
        device.recovery_codes = [c for c in device.recovery_codes if c != hashed]
        device.save(update_fields=["recovery_codes"])
        return True
    return False


def has_two_factor(user):
    device = getattr(user, "two_factor", None)
    return bool(device and device.confirmed)


def two_factor_required(user):
    from core.models import HotelSettings

    return (HotelSettings.load().require_two_factor_for_managers
            and user.has_role(user.Role.MANAGER) and not has_two_factor(user))


# ------------------------------------------------------------------------------ lockout
def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR", ""))[:64]


def lockout_status(username, ip):
    """Return minutes remaining if this username or IP is locked out, else 0."""
    from .models import LoginAttempt

    window = datetime.timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
    since = timezone.now() - window
    failures = LoginAttempt.objects.filter(successful=False, created_at__gte=since)
    user_failures = failures.filter(username__iexact=username).order_by("-created_at")
    ip_failures = failures.filter(ip_address=ip).order_by("-created_at") if ip else failures.none()
    for qs, limit in ((user_failures, settings.LOGIN_LOCKOUT_ATTEMPTS),
                      (ip_failures, settings.LOGIN_LOCKOUT_ATTEMPTS * 4)):
        attempts = list(qs.values_list("created_at", flat=True)[:limit])
        if len(attempts) >= limit:
            unlock = attempts[-1] + window
            remaining = (unlock - timezone.now()).total_seconds()
            if remaining > 0:
                return max(1, int(remaining // 60) + 1)
    return 0


def record_attempt(username, ip, successful):
    from .models import LoginAttempt

    LoginAttempt.objects.create(username=(username or "")[:150], ip_address=ip, successful=successful)
    if successful:  # a good login clears this user's failure streak
        LoginAttempt.objects.filter(username__iexact=username, successful=False).delete()
