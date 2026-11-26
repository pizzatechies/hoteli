from decimal import Decimal

from django.core import mail
from django.test import override_settings
from django.urls import reverse

from bookings.models import Booking
from core.models import HotelSettings
from hoteli.testutils import HotelTestCase
from mpesa.models import MpesaTransaction
from website.models import ContactMessage


@override_settings(MPESA_SIMULATE=True)
class WebsiteBookingTests(HotelTestCase):
    def search_params(self, ci=1, co=3, adults=2):
        return {"check_in": self.day(ci).isoformat(), "check_out": self.day(co).isoformat(),
                "adults": adults, "children": 0}

    def guest_data(self, **extra):
        return {"first_name": "Wanjiru", "last_name": "Kamau", "phone": "0722 000 111",
                "email": "wanjiru@example.com", "accept_terms": "on", **extra}

    def test_public_pages(self):
        for name in ["home", "rooms", "dining", "facilities", "contact", "search", "lookup"]:
            self.assertEqual(self.client.get(reverse(f"website:{name}")).status_code, 200, name)
        self.assertContains(self.client.get(reverse("website:room_detail", args=[self.std.pk])), "Standard")
        self.assertContains(self.client.get(reverse("website:home")), "Crafted by <strong class=\"text-white\">Pizza Technologies</strong>", html=False)

    def test_search_lists_available_types_with_quote(self):
        resp = self.client.get(reverse("website:search"), self.search_params())
        self.assertContains(resp, "Standard")
        self.assertContains(resp, "10,000")  # 2 nights x 5,000

    def test_search_rejects_past_dates(self):
        resp = self.client.get(reverse("website:search"), self.search_params(ci=-1, co=1))
        self.assertContains(resp, "cannot be in the past")

    def test_full_online_booking_with_mpesa_deposit(self):
        url = reverse("website:book", args=[self.std.pk]) + "?" + "&".join(
            f"{k}={v}" for k, v in self.search_params().items())
        resp = self.client.post(url, self.guest_data())
        booking = Booking.objects.get(source=Booking.Source.WEBSITE)
        self.assertRedirects(resp, reverse("website:booking", args=[booking.public_token]))
        self.assertEqual(booking.status, Booking.Status.PENDING)
        self.assertEqual(booking.deposit_required, Decimal("5000"))  # 50% of 10,000
        self.assertIsNotNone(booking.expires_at)

        page = self.client.get(reverse("website:booking", args=[booking.public_token]))
        self.assertContains(page, "Pay your deposit")

        resp = self.client.post(reverse("website:booking_pay", args=[booking.public_token]),
                                {"phone": "0722000111", "amount": "1"}, HTTP_ACCEPT="application/json")
        tx = MpesaTransaction.objects.get(uuid=resp.json()["id"])
        self.assertEqual(tx.amount, Decimal("5000"))  # deposit amount enforced server-side
        self.assertEqual(tx.source, MpesaTransaction.Source.WEBSITE)

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("mpesa:simulate", args=[tx.uuid]), {"outcome": "success"})
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertContains(self.client.get(reverse("website:booking", args=[booking.public_token])),
                            "Your booking is confirmed")

    def test_no_deposit_mode_confirms_immediately(self):
        hotel = HotelSettings.objects.get_or_create(pk=1)[0]
        hotel.website_require_deposit = False
        hotel.save()
        url = reverse("website:book", args=[self.std.pk]) + "?" + "&".join(
            f"{k}={v}" for k, v in self.search_params().items())
        self.client.post(url, self.guest_data())
        self.assertEqual(Booking.objects.get().status, Booking.Status.CONFIRMED)

    def test_sold_out_message(self):
        self.make_booking(room=self.r101, ci=1, co=3)
        self.make_booking(room=self.r102, ci=1, co=3)
        url = reverse("website:book", args=[self.std.pk]) + "?" + "&".join(
            f"{k}={v}" for k, v in self.search_params().items())
        resp = self.client.post(url, self.guest_data())
        self.assertContains(resp, "sold out")

    def test_existing_guest_is_reused(self):
        url = reverse("website:book", args=[self.std.pk]) + "?" + "&".join(
            f"{k}={v}" for k, v in self.search_params().items())
        self.client.post(url, self.guest_data(first_name="Jane", email="jane@example.com", phone="+254712345678"))
        self.assertEqual(Booking.objects.get().guest, self.guest)

    def test_honeypot_blocks_bots(self):
        url = reverse("website:book", args=[self.std.pk]) + "?" + "&".join(
            f"{k}={v}" for k, v in self.search_params().items())
        self.client.post(url, self.guest_data(website="http://spam"))
        self.assertFalse(Booking.objects.exists())

    def test_lookup_by_phone_in_any_format(self):
        booking = self.make_booking(ci=1, co=2)
        resp = self.client.post(reverse("website:lookup"), {"reference": booking.reference.lower(),
                                                            "contact": "+254 712 345 678"})
        self.assertRedirects(resp, reverse("website:booking", args=[booking.public_token]))
        resp = self.client.post(reverse("website:lookup"), {"reference": booking.reference, "contact": "0799999999"})
        self.assertContains(resp, "couldn&#x27;t find")

    def test_contact_form(self):
        self.client.post(reverse("website:contact"), {"name": "Tom", "email": "tom@example.com", "subject": "Hi",
                                                      "message": "Do you have a pool?"})
        self.assertEqual(ContactMessage.objects.count(), 1)
        self.login(self.reception)
        self.assertContains(self.client.get(reverse("website:inbox")), "Do you have a pool?")


class WebsiteBuilderTests(HotelTestCase):
    def setUp(self):
        super().setUp()
        from website import builder

        self.builder = builder

    def test_manager_creates_page_from_template_and_publishes(self):
        from website.models import Page

        self.login(self.manager)
        resp = self.client.post(reverse("website:builder_page_create"), {"title": "Events & Weddings", "template": "events"})
        page = Page.objects.get()
        self.assertRedirects(resp, reverse("website:builder_page", args=[page.pk]))
        self.assertEqual(page.slug, "events-weddings")
        self.assertGreater(page.sections.count(), 2)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("website:page", args=[page.slug])).status_code, 404)
        self.login(self.manager)
        self.assertContains(self.client.get(reverse("website:page", args=[page.slug])), "this page is a draft")
        self.client.post(reverse("website:builder_page_action", args=[page.pk, "publish"]))
        self.client.logout()
        resp = self.client.get(reverse("website:page", args=[page.slug]))
        self.assertContains(resp, "Conferences, workshops")
        self.assertContains(self.client.get("/"), "Events &amp; Weddings")  # appears in the menu

    def test_builder_page_replaces_homepage(self):
        page = self.builder.create_page(title="Home", template="home", is_home=True, is_published=True)
        hero = page.sections.get(kind="HERO")
        hero.title = "Karibu to our lakeside lodge"
        hero.save()
        resp = self.client.get("/")
        self.assertContains(resp, "Karibu to our lakeside lodge")
        self.assertContains(resp, "Standard")  # rooms section
        self.assertContains(resp, 'name="check_in"')  # booking search
        second = self.builder.create_page(title="Home 2", is_home=True, is_published=True)
        page.refresh_from_db()
        self.assertFalse(page.is_home)
        self.assertTrue(second.is_home)

    def test_section_add_edit_move_hide_delete(self):
        page = self.builder.create_page(title="Info", is_published=True)
        self.login(self.manager)
        self.client.post(reverse("website:builder_section_add", args=[page.pk]), {"kind": "TEXT"})
        self.client.post(reverse("website:builder_section_add", args=[page.pk]), {"kind": "FAQ"})
        text, faq = page.sections.order_by("order")
        resp = self.client.post(reverse("website:builder_section", args=[text.pk]), {
            "title": "House rules", "body": "No smoking.\n\nQuiet hours 10pm.", "align": "left",
            "background": "soft", "is_visible": "on", "eyebrow": "",
        })
        self.assertRedirects(resp, reverse("website:builder_section", args=[text.pk]))
        self.client.post(reverse("website:builder_section_action", args=[faq.pk, "up"]))
        self.assertEqual(list(page.sections.order_by("order").values_list("kind", flat=True)), ["FAQ", "TEXT"])
        self.client.post(reverse("website:builder_section_action", args=[text.pk, "duplicate"]))
        self.assertEqual(page.sections.filter(kind="TEXT").count(), 2)
        self.client.post(reverse("website:builder_section_action", args=[faq.pk, "toggle"]))
        public = self.client.get(reverse("website:page", args=[page.slug]))
        self.assertContains(public, "House rules")
        self.assertContains(public, "Quiet hours 10pm.")
        self.assertNotContains(public, "What time is check-in?")
        self.client.post(reverse("website:builder_section_action", args=[faq.pk, "delete"]))
        self.assertFalse(page.sections.filter(kind="FAQ").exists())

    def test_unsafe_links_and_colours_rejected(self):
        page = self.builder.create_page(title="Promo", template="blank")
        section = self.builder.add_section(page, "CTA")
        self.login(self.manager)
        resp = self.client.post(reverse("website:builder_section", args=[section.pk]), {
            "title": "x", "button_text": "Click", "button_url": "javascript:alert(1)", "background": "brand",
            "is_visible": "on",
        })
        self.assertContains(resp, "Links must start with")
        for bad in ["red;}</style><script>", "#zzzzzz"]:
            resp = self.client.post(reverse("website:builder"), {
                "theme-primary_color": bad, "theme-accent_color": "#d97706",
                "theme-dark_color": "#0f172a", "theme-heading_font": "Lora",
            })
            self.assertEqual(resp.status_code, 200)  # re-rendered with errors, not saved
            self.assertTrue(resp.context["theme_form"].errors)
        self.assertContains(resp, "hex colour")
        self.client.post(reverse("website:builder"), {
            "theme-primary_color": "#7c3aed", "theme-accent_color": "#d97706", "theme-dark_color": "#0f172a",
            "theme-heading_font": "Lora",
        })
        self.client.logout()
        resp = self.client.get("/")
        self.assertContains(resp, "--brand:#7c3aed")
        self.assertContains(resp, "family=Lora")

    def test_text_is_escaped(self):
        page = self.builder.create_page(title="Safe", is_published=True)
        self.builder.add_section(page, "TEXT", {"title": "<script>alert(1)</script>", "body": "<b>hi</b>"})
        resp = self.client.get(reverse("website:page", args=[page.slug]))
        self.assertNotContains(resp, "<script>alert(1)</script>")
        self.assertContains(resp, "&lt;b&gt;hi&lt;/b&gt;")

    def test_contact_section_returns_to_page(self):
        page = self.builder.create_page(title="Venue", template="contact", is_published=True)
        resp = self.client.post(reverse("website:contact"), {
            "name": "Tom", "email": "tom@example.com", "subject": "Quote", "message": "Hi", "next": page.get_absolute_url(),
        })
        self.assertRedirects(resp, page.get_absolute_url())
        resp = self.client.post(reverse("website:contact"), {
            "name": "Tom", "email": "tom@example.com", "subject": "Quote", "message": "Hi", "next": "https://evil.example/",
        })
        self.assertRedirects(resp, reverse("website:contact"))

    def test_only_managers_can_use_builder(self):
        self.login(self.reception)
        self.assertEqual(self.client.get(reverse("website:builder")).status_code, 403)
        self.login(self.manager)
        self.assertEqual(self.client.get(reverse("website:builder")).status_code, 200)

    def test_every_section_type_renders(self):
        from website.models import Section

        page = self.builder.create_page(title="All", is_published=True)
        for kind in Section.Kind.values:
            self.builder.add_section(page, kind)
        resp = self.client.get(reverse("website:page", args=[page.slug]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Frequently asked questions")
        self.assertContains(resp, "Why book direct")


class GuestFeedbackTests(HotelTestCase):
    def checkout(self):
        from bookings import services as booking_services

        b = self.make_booking(ci=-1, co=0, status=Booking.Status.CHECKED_IN)
        with self.captureOnCommitCallbacks(execute=True):
            booking_services.check_out(b, allow_balance=True)
        return b

    def test_feedback_requested_at_checkout_and_published_to_website(self):
        from notifications.models import SmsMessage
        from website.models import GuestFeedback

        b = self.checkout()
        fb = GuestFeedback.objects.get(booking=b)
        self.assertTrue(SmsMessage.objects.filter(kind="FEEDBACK", body__contains=str(fb.token)).exists())
        self.assertEqual(len(mail.outbox), 1)
        url = reverse("website:feedback", args=[fb.token])
        self.assertContains(self.client.get(url), "How was your stay")
        self.assertContains(self.client.post(url, {"rating": "9"}), "1 to 5 stars")
        self.client.post(url, {"rating": "5", "comment": "Lovely staff and great breakfast."})
        fb.refresh_from_db()
        self.assertEqual(fb.rating, 5)
        self.client.post(url, {"rating": "1", "comment": "changed my mind"})  # can't overwrite
        fb.refresh_from_db()
        self.assertEqual(fb.rating, 5)
        self.login(self.manager)
        self.assertContains(self.client.get(reverse("website:feedback_list")), "great breakfast")
        self.client.post(reverse("website:feedback_publish", args=[fb.pk]))
        from website import builder

        page = builder.create_page(title="Reviews", is_published=True)
        builder.add_section(page, "TESTIMONIALS")
        self.client.logout()
        resp = self.client.get(reverse("website:page", args=[page.slug]))
        self.assertContains(resp, "Lovely staff and great breakfast.")
        self.assertContains(resp, "Jane D.")
        self.assertNotContains(resp, "Jane Doe")

    def test_feedback_can_be_switched_off(self):
        from core.models import HotelSettings
        from website.models import GuestFeedback

        hotel = HotelSettings.objects.get_or_create(pk=1)[0]
        hotel.feedback_requests = False
        hotel.save()
        self.checkout()
        self.assertFalse(GuestFeedback.objects.exists())
