"""Minimal, dependency-free iCalendar (RFC 5545) reading and writing for room availability."""

import datetime
import ipaddress
import socket
from urllib.parse import urlparse

import requests

MAX_BYTES = 2 * 1024 * 1024


class CalendarError(Exception):
    pass


def check_public_https(url):
    """Refuse non-HTTPS links and links that point into private networks (SSRF protection)."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise CalendarError("Use the https:// calendar link from the other site.")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise CalendarError(f"Can't find {parsed.hostname}.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise CalendarError("That link points to a private network address.")


def fetch(url):
    check_public_https(url)
    try:
        resp = requests.get(url, timeout=20, stream=True, allow_redirects=False,
                            headers={"User-Agent": "Hoteli calendar sync"})
    except requests.RequestException as exc:
        raise CalendarError(f"Couldn't download the calendar ({exc.__class__.__name__}).") from exc
    if resp.is_redirect:
        location = resp.headers.get("Location", "")
        check_public_https(location)
        resp = requests.get(location, timeout=20, stream=True, allow_redirects=False,
                            headers={"User-Agent": "Hoteli calendar sync"})
    if resp.status_code != 200:
        raise CalendarError(f"The calendar link returned HTTP {resp.status_code}.")
    body = b""
    for chunk in resp.iter_content(65536):
        body += chunk
        if len(body) > MAX_BYTES:
            raise CalendarError("The calendar is too large.")
    text = body.decode("utf-8", errors="replace")
    if "BEGIN:VCALENDAR" not in text:
        raise CalendarError("That link isn't an iCal calendar.")
    return text


def _unfold(text):
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _parse_date(value):
    value = value.strip()
    try:
        if "T" in value:
            stamp = datetime.datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
            if value.endswith("Z"):
                from django.utils import timezone

                stamp = timezone.localtime(stamp.replace(tzinfo=datetime.timezone.utc))
            return stamp.date()
        return datetime.datetime.strptime(value[:8], "%Y%m%d").date()
    except ValueError:
        return None


def parse_events(text):
    """Yield dicts {uid, start, end, summary} for VEVENTs that are not cancelled."""
    event = None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            event = {}
            continue
        if line == "END:VEVENT":
            if event and event.get("start") and event.get("status", "").upper() != "CANCELLED":
                start = event["start"]
                end = event.get("end") or start + datetime.timedelta(days=1)
                if end <= start:
                    end = start + datetime.timedelta(days=1)
                uid = event.get("uid") or f"{start:%Y%m%d}-{end:%Y%m%d}"
                yield {"uid": uid[:255], "start": start, "end": end, "summary": event.get("summary", "")[:200]}
            event = None
            continue
        if event is None or ":" not in line:
            continue
        key, value = line.split(":", 1)
        name = key.split(";", 1)[0].upper()
        if name == "UID":
            event["uid"] = value.strip()
        elif name == "DTSTART":
            event["start"] = _parse_date(value)
        elif name == "DTEND":
            event["end"] = _parse_date(value)
        elif name == "SUMMARY":
            event["summary"] = value.replace("\\,", ",").replace("\\n", " ").strip()
        elif name == "STATUS":
            event["status"] = value.strip()


def _escape(text):
    return text.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\;").replace("\n", "\\n")


def build_calendar(name, events):
    """events: iterable of (uid, start_date, end_date, summary). All-day events, no guest details."""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Hoteli//Room availability//EN", "CALSCALE:GREGORIAN",
           "METHOD:PUBLISH", f"X-WR-CALNAME:{_escape(name)}"]
    for uid, start, end, summary in events:
        out += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}", f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
                f"DTEND;VALUE=DATE:{end:%Y%m%d}", f"SUMMARY:{_escape(summary)}", "TRANSP:OPAQUE", "END:VEVENT"]
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"
