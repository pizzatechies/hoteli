import datetime
from unittest import mock

from django.urls import reverse

from bookings import services
from bookings.services import BookingError
from channel_sync import ical
from channel_sync.models import ChannelCalendar, RoomBlock
from channel_sync.services import sync_calendar
from hoteli.testutils import HotelTestCase


def feed_text(events):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Booking.com//EN"]
    for uid, start, end, extra in events:
        lines += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
                  f"DTEND;VALUE=DATE:{end:%Y%m%d}", "SUMMARY:CLOSED - Not available", *extra, "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


class IcalParsingTests(HotelTestCase):
    def test_parses_dates_datetimes_folding_and_cancellations(self):
        text = (
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:abc\r\nDTSTART;VALUE=DATE:20261201\r\nDTEND;VALUE=DATE:20261204\r\n"
            "SUMMARY:Airbnb (Not avail\r\n able)\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:def\r\nDTSTART:20261210T120000Z\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:ghi\r\nDTSTART;VALUE=DATE:20261215\r\nDTEND;VALUE=DATE:20261216\r\n"
            "STATUS:CANCELLED\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        events = list(ical.parse_events(text))
        self.assertEqual([e["uid"] for e in events], ["abc", "def"])
        self.assertEqual(events[0]["summary"], "Airbnb (Not available)")
        self.assertEqual((events[0]["start"], events[0]["end"]), (datetime.date(2026, 12, 1), datetime.date(2026, 12, 4)))
        self.assertEqual(events[1]["end"] - events[1]["start"], datetime.timedelta(days=1))

    def test_rejects_private_and_plain_http_links(self):
        with self.assertRaisesMessage(ical.CalendarError, "https"):
            ical.check_public_https("http://example.com/cal.ics")
        with mock.patch("channel_sync.ical.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.5", 443))]):
            with self.assertRaisesMessage(ical.CalendarError, "private network"):
                ical.check_public_https("https://intranet.example/cal.ics")
        with mock.patch("channel_sync.ical.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("169.254.169.254", 443))]):
            with self.assertRaises(ical.CalendarError):
                ical.check_public_https("https://metadata.example/latest")


class SyncTests(HotelTestCase):
    def setUp(self):
        super().setUp()
        self.cal = ChannelCalendar.objects.create(room=self.r101, name="Booking.com",
                                                  import_url="https://admin.booking.com/ical/123.ics")

    def sync(self, events):
        with mock.patch("channel_sync.ical.fetch", return_value=feed_text(events)):
            return sync_calendar(self.cal)

    def test_imported_reservation_blocks_room_everywhere(self):
        self.assertEqual(self.sync([("bk-1", self.day(2), self.day(5), [])]), (1, 0, 0))
        self.assertFalse(services.available_rooms(self.day(3), self.day(4)).filter(pk=self.r101.pk).exists())
        self.assertTrue(services.available_rooms(self.day(5), self.day(6)).filter(pk=self.r101.pk).exists())
        with self.assertRaisesMessage(BookingError, "blocked by Booking.com"):
            services.create_booking(guest=self.guest, room=self.r101, check_in=self.day(4), check_out=self.day(6))

    def test_cancellation_on_the_other_site_removes_block(self):
        self.sync([("bk-1", self.day(2), self.day(5), []), ("bk-2", self.day(8), self.day(9), [])])
        self.assertEqual(RoomBlock.objects.count(), 2)
        self.assertEqual(self.sync([("bk-2", self.day(8), self.day(10), [])]), (0, 1, 1))
        block = RoomBlock.objects.get()
        self.assertEqual(block.end_date, self.day(10))

    def test_overlap_with_our_booking_is_flagged(self):
        b = self.make_booking(ci=2, co=4)
        self.sync([("bk-1", self.day(3), self.day(6), [])])
        self.assertIn(b.reference, RoomBlock.objects.get().conflict)
        self.login(self.reception)
        self.assertContains(self.client.get(reverse("channel_sync:list")), "Possible double bookings")

    def test_failed_download_is_recorded(self):
        with mock.patch("channel_sync.ical.fetch", side_effect=ical.CalendarError("The calendar link returned HTTP 404.")):
            with self.assertRaises(ical.CalendarError):
                sync_calendar(self.cal)
        self.cal.refresh_from_db()
        self.assertIn("404", self.cal.last_error)

    def test_export_feed_has_no_guest_details(self):
        self.make_booking(ci=1, co=3)
        other = ChannelCalendar.objects.create(room=self.r101, name="Airbnb")
        self.sync([("bk-1", self.day(5), self.day(7), [])])
        resp = self.client.get(reverse("channel_sync:feed", args=[other.export_token]))
        self.assertEqual(resp["Content-Type"], "text/calendar; charset=utf-8")
        body = resp.content.decode()
        self.assertIn(f"DTSTART;VALUE=DATE:{self.day(1):%Y%m%d}", body)
        self.assertIn(f"DTSTART;VALUE=DATE:{self.day(5):%Y%m%d}", body)  # Booking.com block shared with Airbnb
        self.assertNotIn("Jane", body)
        self.assertNotIn("Doe", body)
        own = self.client.get(reverse("channel_sync:feed", args=[self.cal.export_token])).content.decode()
        self.assertNotIn(f"{self.day(5):%Y%m%d}", own)  # don't echo a site's own reservations back to it

    def test_manual_block_and_tape_chart(self):
        self.login(self.reception)
        self.client.post(reverse("channel_sync:block_create"), {"room": self.r102.pk, "start_date": self.day(1),
                                                                 "end_date": self.day(3), "summary": "Owner stay"})
        self.assertTrue(RoomBlock.objects.filter(room=self.r102, calendar__isnull=True).exists())
        self.assertContains(self.client.get(reverse("bookings:tape_chart")), "Manual block")

    def test_only_managers_connect_calendars(self):
        self.login(self.reception)
        self.assertEqual(self.client.get(reverse("channel_sync:create")).status_code, 403)
        self.login(self.manager)
        resp = self.client.post(reverse("channel_sync:create"), {"room": self.r102.pk, "name": "Airbnb",
                                                                 "import_url": "http://airbnb.example/x.ics",
                                                                 "is_active": "on"})
        self.assertContains(resp, "https://")
