"""Shared fixtures for the test-suite."""

import datetime
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from bookings.models import Booking, Guest
from rooms.models import Room, RoomType


class HotelTestCase(TestCase):
    password = "pass12345!"

    def setUp(self):
        cache.clear()
        self.today = timezone.localdate()
        self.std = RoomType.objects.create(name="Standard", base_rate=Decimal("5000"), max_adults=2, max_children=1)
        self.suite = RoomType.objects.create(name="Suite", base_rate=Decimal("12000"), max_adults=3, max_children=2)
        self.r101 = Room.objects.create(number="101", room_type=self.std, floor="1")
        self.r102 = Room.objects.create(number="102", room_type=self.std, floor="1")
        self.r301 = Room.objects.create(number="301", room_type=self.suite, floor="3")
        self.guest = Guest.objects.create(first_name="Jane", last_name="Doe", phone="0712345678",
                                          email="jane@example.com", id_number="12345678")
        self.admin = self.make_user("boss", User.Role.ADMIN, superuser=True)
        self.manager = self.make_user("manager", User.Role.MANAGER)
        self.reception = self.make_user("frontdesk", User.Role.RECEPTIONIST)
        self.accountant = self.make_user("accounts", User.Role.ACCOUNTANT)
        self.hk = self.make_user("hk", User.Role.HOUSEKEEPING)
        self.waiter = self.make_user("waiter", User.Role.RESTAURANT)

    def make_user(self, username, role, superuser=False):
        user = User(username=username, role=role, is_superuser=superuser, is_staff=superuser)
        user.set_password(self.password)
        user.save()
        return user

    def login(self, user):
        self.client.login(username=user.username, password=self.password)

    def day(self, offset):
        return self.today + datetime.timedelta(days=offset)

    def make_booking(self, room=None, ci=0, co=2, status=Booking.Status.CONFIRMED, guest=None, **extra):
        return Booking.objects.create(
            guest=guest or self.guest, room=room or self.r101, check_in_date=self.day(ci),
            check_out_date=self.day(co), rate=(room or self.r101).room_type.base_rate, status=status, **extra,
        )
