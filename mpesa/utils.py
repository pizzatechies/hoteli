import datetime
import re
from decimal import ROUND_CEILING, Decimal
from zoneinfo import ZoneInfo

NAIROBI = ZoneInfo("Africa/Nairobi")
MAX_STK_AMOUNT = Decimal("250000")


def normalize_phone(raw):
    """Return a Kenyan mobile number in Daraja's 2547XXXXXXXX / 2541XXXXXXXX format.

    Accepts 0712345678, 712345678, +254712345678, 254 712 345 678, 0110 123 456, etc.
    Raises ValueError for anything that is not a Kenyan mobile number.
    """
    digits = re.sub(r"\D", "", str(raw or ""))
    if digits.startswith("254") and len(digits) == 12:
        number = digits
    elif digits.startswith("0") and len(digits) == 10:
        number = "254" + digits[1:]
    elif len(digits) == 9:
        number = "254" + digits
    else:
        raise ValueError("Enter a valid Kenyan mobile number, e.g. 0712 345 678.")
    if number[3] not in "17":
        raise ValueError("Enter a valid Kenyan mobile number, e.g. 0712 345 678.")
    return number


def stk_amount(amount):
    """M-Pesa only takes whole shillings: round up, enforce the KES 1 – 250,000 limits."""
    value = Decimal(str(amount)).quantize(Decimal("1"), rounding=ROUND_CEILING)
    if value < 1:
        raise ValueError("Amount must be at least KES 1.")
    if value > MAX_STK_AMOUNT:
        raise ValueError("M-Pesa allows at most KES 250,000 per transaction. Split the payment.")
    return value


def parse_mpesa_timestamp(value):
    """Parse Daraja's YYYYMMDDHHMMSS (number or string, Nairobi time) into an aware datetime."""
    if value in (None, ""):
        return None
    try:
        naive = datetime.datetime.strptime(str(value).split(".")[0], "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return naive.replace(tzinfo=NAIROBI)


def daraja_timestamp(now=None):
    now = now or datetime.datetime.now(tz=NAIROBI)
    return now.astimezone(NAIROBI).strftime("%Y%m%d%H%M%S")
