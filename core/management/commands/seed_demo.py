import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from bookings.models import Booking, Charge, Guest, Payment
from bookings.services import post_room_charges, record_payment
from core.models import HotelSettings
from housekeeping.models import HousekeepingTask, MaintenanceRequest
from pos.models import MenuCategory, MenuItem
from rooms.models import Room, RoomType, SeasonalRate
from website.builder import IMG as BUILDER_IMG
from website.builder import create_page
from website.models import Facility, Page, WebsiteContent

IMG = "https://images.unsplash.com/{}?auto=format&fit=crop&w=1200&q=70"

ROOM_TYPES = [
    {
        "name": "Standard Room", "base_rate": "4500", "max_adults": 2, "max_children": 0, "bed_type": "Double bed",
        "size_sqm": 20, "display_order": 1, "image": "photo-1631049307264-da0ec9d70304",
        "amenities": "Free Wi-Fi, Smart TV, Hot shower, Work desk, Tea & coffee",
        "description": "A bright, comfortable room with a double bed, en-suite shower and everything you need "
                       "for a restful night – ideal for solo travellers and couples.",
        "rooms": ["101", "102", "103", "104", "105", "106", "107", "108"], "floor": "1",
    },
    {
        "name": "Deluxe Room", "base_rate": "7500", "max_adults": 2, "max_children": 1, "bed_type": "King bed",
        "size_sqm": 28, "display_order": 2, "image": "photo-1590490360182-c33d57733427",
        "amenities": "Free Wi-Fi, Smart TV, Air conditioning, Minibar, Balcony, Bathtub",
        "description": "Spacious and stylish with a king-size bed, a private balcony and a bathtub. "
                       "Includes a minibar and air conditioning.",
        "rooms": ["201", "202", "203", "204", "205", "206"], "floor": "2",
    },
    {
        "name": "Family Room", "base_rate": "9500", "max_adults": 2, "max_children": 3, "bed_type": "Queen + 2 singles",
        "size_sqm": 36, "display_order": 3, "image": "photo-1611892440504-42a792e24d32",
        "amenities": "Free Wi-Fi, Smart TV, Air conditioning, Sofa area, Fridge",
        "description": "Room for the whole family: a queen bed plus two single beds, a sofa corner and fridge.",
        "rooms": ["301", "302"], "floor": "3",
    },
    {
        "name": "Executive Suite", "base_rate": "14000", "max_adults": 3, "max_children": 2, "bed_type": "King bed",
        "size_sqm": 52, "display_order": 4, "image": "photo-1582719478250-c89cae4dc85b",
        "amenities": "Free Wi-Fi, Separate lounge, Air conditioning, Minibar, Bathtub, Nespresso machine, City view",
        "description": "Our finest accommodation – a separate lounge, king bedroom, city views and premium amenities.",
        "rooms": ["303", "304"], "floor": "3",
    },
]

MENU = {
    "Breakfast": [("Full Kenyan breakfast", "950", "FOOD", "Eggs, sausages, toast, fruit and tea or coffee"),
                  ("Continental breakfast", "750", "FOOD", "Pastries, fruit, yoghurt and juice"),
                  ("Mandazi & chai", "250", "FOOD", "")],
    "Mains": [("Nyama choma (½ kg)", "1200", "FOOD", "Grilled goat with kachumbari and ugali"),
              ("Tilapia fry with ugali", "1350", "FOOD", "Whole fried tilapia, sukuma wiki"),
              ("Chicken tikka", "1100", "FOOD", "With rice or chapati"),
              ("Beef stew & chapati", "850", "FOOD", ""),
              ("Vegetable biryani", "900", "FOOD", "")],
    "Snacks": [("Beef samosas (3)", "300", "FOOD", ""), ("Chips masala", "450", "FOOD", ""),
               ("Chicken wings", "750", "FOOD", "")],
    "Drinks": [("Tusker lager", "350", "BEVERAGE", ""), ("Soda 500ml", "120", "BEVERAGE", ""),
               ("Fresh passion juice", "300", "BEVERAGE", ""), ("Dawa cocktail", "650", "BEVERAGE", ""),
               ("Kenyan coffee", "250", "BEVERAGE", ""), ("Mineral water 1L", "150", "BEVERAGE", "")],
}

FACILITIES = [
    ("Free high-speed Wi-Fi", "wifi", "Fast fibre internet in every room and public area."),
    ("Restaurant & bar", "cup-hot", "Kenyan and international dishes, open 6:30am – 11pm."),
    ("Secure parking", "p-circle", "Free, guarded parking with CCTV."),
    ("Swimming pool", "water", "Heated outdoor pool with loungers."),
    ("Conference rooms", "easel", "Meeting spaces for 10 – 120 people with projector."),
    ("Airport transfers", "airplane", "JKIA and Wilson pick-ups on request."),
    ("Laundry service", "basket", "Same-day laundry and ironing."),
    ("24-hour front desk", "clock-history", "Our team is available around the clock."),
]

STAFF = [
    ("admin", "Admin", "User", User.Role.ADMIN, True),
    ("manager", "Mary", "Wanjiku", User.Role.MANAGER, False),
    ("reception", "Brian", "Otieno", User.Role.RECEPTIONIST, False),
    ("accounts", "Grace", "Achieng", User.Role.ACCOUNTANT, False),
    ("housekeeping", "Joseph", "Kamau", User.Role.HOUSEKEEPING, False),
    ("restaurant", "Faith", "Mutua", User.Role.RESTAURANT, False),
]

GUESTS = [
    ("Daniel", "Kiprotich", "0712345678", "daniel@example.com", "23456789", "Kenyan"),
    ("Aisha", "Mohamed", "0723456789", "aisha@example.com", "34567890", "Kenyan"),
    ("Peter", "Mwangi", "0734567890", "peter@example.com", "45678901", "Kenyan"),
    ("Sarah", "Johnson", "+447700900123", "sarah@example.com", "P1234567", "British"),
    ("Kevin", "Odhiambo", "0745678901", "", "56789012", "Kenyan"),
    ("Lucy", "Njeri", "0756789012", "lucy@example.com", "67890123", "Kenyan"),
    ("Samuel", "Tesfaye", "+251911234567", "", "EP998877", "Ethiopian"),
]


class Command(BaseCommand):
    help = "Load demo data: staff accounts, rooms, rates, menu, website content, guests and bookings."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="demo12345", help="Password for all demo staff accounts.")
        parser.add_argument("--no-bookings", action="store_true", help="Skip demo guests and bookings.")

    @transaction.atomic
    def handle(self, *args, **opts):
        hotel = HotelSettings.load()
        hotel = HotelSettings.objects.get(pk=hotel.pk)
        if hotel.name == "Hoteli Grand" and not hotel.kra_pin:
            hotel.address = "Kenyatta Avenue, Nairobi, Kenya"
            hotel.phone = "+254 700 123 456"
            hotel.kra_pin = "P051234567X"
            hotel.save()
        content, _ = WebsiteContent.objects.get_or_create(pk=1)
        if not content.whatsapp_number:
            content.whatsapp_number = "254700123456"
            content.save()

        for username, first, last, role, is_super in STAFF:
            if not User.objects.filter(username=username).exists():
                user = User(username=username, first_name=first, last_name=last, role=role,
                            is_superuser=is_super, is_staff=is_super, email=f"{username}@hoteli.local")
                user.set_password(opts["password"])
                user.save()
        self.stdout.write(self.style.SUCCESS(
            f"Staff logins (password '{opts['password']}'): " + ", ".join(s[0] for s in STAFF)
        ))

        for i, (name, icon, desc) in enumerate(FACILITIES):
            Facility.objects.get_or_create(name=name, defaults={"icon": icon, "description": desc, "display_order": i})

        if not RoomType.objects.exists():
            today = timezone.localdate()
            festive_start = datetime.date(today.year, 12, 20)
            for spec in ROOM_TYPES:
                rt = RoomType.objects.create(
                    name=spec["name"], base_rate=Decimal(spec["base_rate"]), max_adults=spec["max_adults"],
                    max_children=spec["max_children"], bed_type=spec["bed_type"], size_sqm=spec["size_sqm"],
                    display_order=spec["display_order"], amenities=spec["amenities"],
                    description=spec["description"], image_url=IMG.format(spec["image"]),
                )
                SeasonalRate.objects.create(
                    room_type=rt, name="Festive season", start_date=festive_start,
                    end_date=datetime.date(today.year + 1, 1, 3), rate=(rt.base_rate * Decimal("1.2")).quantize(Decimal("1")),
                )
                for number in spec["rooms"]:
                    Room.objects.create(number=number, room_type=rt, floor=spec["floor"])
            self.stdout.write(self.style.SUCCESS(f"Created {RoomType.objects.count()} room types and {Room.objects.count()} rooms."))

        if not MenuCategory.objects.exists():
            for order, (cat_name, items) in enumerate(MENU.items()):
                cat = MenuCategory.objects.create(name=cat_name, display_order=order)
                for name, price, kind, desc in items:
                    MenuItem.objects.create(category=cat, name=name, price=Decimal(price), kind=kind, description=desc)
            self.stdout.write(self.style.SUCCESS("Created restaurant & bar menu."))

        if not Page.objects.exists():
            create_page(title="Home", template="home", slug="home", is_home=True, is_published=True,
                        show_in_nav=False, meta_description="Book direct and pay with M-Pesa.")
            events = create_page(title="Events & conferences", template="events", slug="events",
                                 is_published=True, nav_label="Events", nav_order=20)
            gallery = events.sections.create(
                kind="GALLERY", order=25, title="Our venues", background="white",
                items="\n".join([
                    BUILDER_IMG.format("photo-1540575467063-178a50c2df87") + " | Main conference hall",
                    BUILDER_IMG.format("photo-1517457373958-b7bdd4587205") + " | Workshops & training",
                    BUILDER_IMG.format("photo-1414235077428-338989a2e8c0") + " | Private dining",
                ]),
            )
            gallery.save()
            create_page(title="About us", template="about", slug="about", is_published=False, nav_order=30)
            self.stdout.write(self.style.SUCCESS("Created website builder pages (Home, Events, About draft)."))

        needed = {"101", "102", "104", "105", "106", "108", "201", "202", "203", "301", "303"}
        if not opts["no_bookings"] and not Booking.objects.exists():
            if needed <= set(Room.objects.values_list("number", flat=True)):
                self._bookings()
            else:
                self.stdout.write(self.style.WARNING(
                    "Skipped demo bookings: this database already has its own rooms."
                ))

    def _bookings(self):
        today = timezone.localdate()
        reception = User.objects.get(username="reception")
        guests = [
            Guest.objects.create(first_name=f, last_name=l, phone=p, email=e, id_number=i, nationality=n,
                                 id_type=Guest.IDType.PASSPORT if not i.isdigit() else Guest.IDType.NATIONAL_ID)
            for f, l, p, e, i, n in GUESTS
        ]
        guests[0].is_vip = True
        guests[0].save()
        room = {r.number: r for r in Room.objects.all()}
        d = lambda n: today + datetime.timedelta(days=n)  # noqa: E731

        def make(guest, number, ci, co, status, source=Booking.Source.WALK_IN, **extra):
            b = Booking.objects.create(
                guest=guest, room=room[number], check_in_date=ci, check_out_date=co, status=status,
                rate=room[number].room_type.base_rate, source=source, created_by=reception,
                adults=extra.pop("adults", 2), **extra,
            )
            return b

        # Departed guest – fully settled
        past = make(guests[2], "201", d(-6), d(-3), Booking.Status.CHECKED_OUT,
                    actual_check_in=timezone.now() - datetime.timedelta(days=6),
                    actual_check_out=timezone.now() - datetime.timedelta(days=3))
        post_room_charges(past, reception)
        Charge.objects.create(booking=past, category=Charge.Category.LAUNDRY, description="Laundry – 5 items",
                              unit_price=Decimal("750"), quantity=1, service_date=d(-4), posted_by=reception)
        record_payment(booking=past, amount=past.charges_total, method=Payment.Method.MPESA,
                       reference="SKD8H2JQ4L", user=reception)

        # In-house guests
        inhouse1 = make(guests[0], "301", d(-2), d(2), Booking.Status.CHECKED_IN, adults=2, children=2,
                        actual_check_in=timezone.now() - datetime.timedelta(days=2))
        post_room_charges(inhouse1, reception, up_to=today)
        record_payment(booking=inhouse1, amount=Decimal("15000"), method=Payment.Method.CASH, user=reception)
        Charge.objects.create(booking=inhouse1, category=Charge.Category.FOOD, description="Restaurant dinner",
                              unit_price=Decimal("3400"), quantity=1, service_date=d(-1), posted_by=reception)
        inhouse2 = make(guests[3], "202", d(-1), d(1), Booking.Status.CHECKED_IN, source=Booking.Source.OTA,
                        actual_check_in=timezone.now() - datetime.timedelta(days=1))
        post_room_charges(inhouse2, reception, up_to=today)
        Room.objects.filter(number__in=["301", "202"]).update(hk_status=Room.HKStatus.CLEAN)

        # Due to leave today
        leaving = make(guests[4], "102", d(-3), today, Booking.Status.CHECKED_IN, adults=1,
                       actual_check_in=timezone.now() - datetime.timedelta(days=3))
        post_room_charges(leaving, reception, up_to=today)
        record_payment(booking=leaving, amount=Decimal("9000"), method=Payment.Method.MPESA,
                       reference="SKE2M4PL9X", user=reception)

        # Arrivals today and upcoming
        make(guests[1], "203", today, d(3), Booking.Status.CONFIRMED, source=Booking.Source.PHONE)
        make(guests[5], "104", today, d(1), Booking.Status.CONFIRMED, adults=1)
        make(guests[6], "303", d(3), d(7), Booking.Status.CONFIRMED, source=Booking.Source.CORPORATE)
        make(guests[2], "105", d(5), d(8), Booking.Status.CONFIRMED, source=Booking.Source.EMAIL)

        # Rooms needing attention
        Room.objects.filter(number__in=["101", "106"]).update(hk_status=Room.HKStatus.DIRTY)
        HousekeepingTask.objects.create(room=room["101"], task_type=HousekeepingTask.TaskType.CHECKOUT_CLEAN,
                                        priority=HousekeepingTask.Priority.HIGH, due_date=today,
                                        assigned_to=User.objects.get(username="housekeeping"))
        mr = MaintenanceRequest.objects.create(room=room["108"], title="Leaking shower mixer",
                                               description="Hot water tap drips constantly.",
                                               priority=MaintenanceRequest.Priority.HIGH,
                                               puts_room_out_of_order=True, reported_by=reception)
        Room.objects.filter(pk=mr.room_id).update(is_out_of_order=True, out_of_order_reason=mr.title)
        self._payments_and_orders(reception, guests, inhouse1, inhouse2)
        self.stdout.write(self.style.SUCCESS(f"Created {Booking.objects.count()} demo bookings."))

    def _payments_and_orders(self, reception, guests, inhouse1, inhouse2):
        """Sample M-Pesa activity, restaurant orders and an inbox message (always simulated)."""
        from django.test.utils import override_settings

        from mpesa import services as mpesa
        from pos import services as pos
        from pos.models import Order
        from website.models import ContactMessage

        arrival = Booking.objects.filter(guest=guests[1]).first()
        with override_settings(MPESA_SIMULATE=True):
            paid = mpesa.initiate_stk_push(phone=guests[0].phone, amount=Decimal("10000"), booking=inhouse1, user=reception)
            mpesa.simulate_result(paid, "success")
            if arrival:
                cancelled = mpesa.initiate_stk_push(phone=guests[1].phone, amount=Decimal("7500"), booking=arrival,
                                                    user=reception)
                mpesa.simulate_result(cancelled, "cancel")
                deposit = mpesa.initiate_stk_push(phone=guests[1].phone, amount=Decimal("7500"), booking=arrival,
                                                  user=reception)
                mpesa.simulate_result(deposit, "success")
        now = timezone.localtime()
        for trans_id, ref, amount, name in [("SKF3L8QZ2D", inhouse2.reference, "5000.00", "SARAH"),
                                            ("SKF4N1WX7R", "ROOM 203", "2500.00", "AISHA")]:
            mpesa.process_c2b_confirmation({
                "TransactionType": "Pay Bill", "TransID": trans_id, "TransTime": now.strftime("%Y%m%d%H%M%S"),
                "TransAmount": amount, "BusinessShortCode": "174379", "BillRefNumber": ref,
                "MSISDN": "2547 ***** 123", "FirstName": name,
            })

        items = {i.name: i for i in MenuItem.objects.all()}
        room_service = Order.objects.create(outlet=Order.Outlet.ROOM_SERVICE, booking=inhouse2,
                                            customer_name=inhouse2.guest.full_name, created_by=reception)
        for name, qty in [("Tilapia fry with ugali", 1), ("Fresh passion juice", 2)]:
            if name in items:
                pos.add_item(room_service, items[name], qty)
        if room_service.items.exists():
            pos.charge_to_room(room_service, reception)
        waiter = User.objects.filter(username="restaurant").first() or reception
        walk_in = Order.objects.create(outlet=Order.Outlet.BAR, table_number="4", customer_name="Walk-in", created_by=waiter)
        for name, qty in [("Tusker lager", 3), ("Chips masala", 1)]:
            if name in items:
                pos.add_item(walk_in, items[name], qty)
        if walk_in.items.exists():
            record_payment(order=walk_in, amount=walk_in.total, method=Payment.Method.CASH, user=waiter)
        lunch = Order.objects.create(outlet=Order.Outlet.RESTAURANT, table_number="7", customer_name="Table 7",
                                     created_by=waiter)
        for name, qty in [("Nyama choma (½ kg)", 2), ("Soda 500ml", 2)]:
            if name in items:
                pos.add_item(lunch, items[name], qty)

        ContactMessage.objects.create(
            name="Event planner (demo)", email="events@example.com", phone="0711000222",
            subject="Conference for 40 people",
            message="Hello, we would like a quote for a one-day conference for 40 people next month, "
                    "including tea breaks and lunch. Do you have a projector?",
        )
