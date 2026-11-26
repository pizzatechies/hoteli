import base64

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from decimal import Decimal

from django.core import mail

from bookings.models import Booking, Payment
from bookings.services import record_payment, send_booking_confirmation
from core.branding import sniff_image
from core.models import AuditLog, BrandAsset, HotelSettings
from hoteli.testutils import HotelTestCase

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><script>alert(1)</script></svg>'


class BrandingTests(HotelTestCase):
    def upload(self, kind, content, name="logo.png"):
        return self.client.post(reverse("core:branding"), {
            "kind": kind, "file": SimpleUploadedFile(name, content, content_type="image/png"),
        })

    def test_sniffing(self):
        self.assertEqual(sniff_image(PNG), "image/png")
        self.assertEqual(sniff_image(b"\xff\xd8\xff\xe0rest"), "image/jpeg")
        self.assertEqual(sniff_image(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "image/webp")
        self.assertEqual(sniff_image(SVG), "image/svg+xml")
        self.assertIsNone(sniff_image(b"<html><script>alert(1)</script></html>"))

    def test_upload_main_logo_shows_everywhere(self):
        self.login(self.manager)
        resp = self.upload("logo", PNG)
        self.assertRedirects(resp, reverse("core:branding"))
        asset = BrandAsset.objects.get(kind="logo")
        self.assertEqual(asset.content_type, "image/png")
        served = self.client.get(asset.url)
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served["Content-Type"], "image/png")
        self.assertEqual(served.content, PNG)
        self.assertIn("immutable", served["Cache-Control"])
        url = asset.url
        self.assertContains(self.client.get(reverse("core:dashboard")), url)  # staff sidebar
        b = self.make_booking()
        self.assertContains(self.client.get(reverse("bookings:invoice", args=[b.pk])), url)
        self.client.logout()
        home = self.client.get("/")
        self.assertContains(home, f'src="{url}"')
        self.assertContains(home, f'rel="icon" href="{url}"')  # favicon falls back to the logo
        self.assertContains(self.client.get(reverse("accounts:login")), url)

    def test_light_logo_and_favicon(self):
        self.login(self.manager)
        self.upload("logo", PNG)
        self.upload("logo-light", PNG)
        self.upload("favicon", PNG, "icon.png")
        light = BrandAsset.objects.get(kind="logo-light").url
        favicon = BrandAsset.objects.get(kind="favicon").url
        self.client.logout()
        home = self.client.get("/")
        self.assertContains(home, light)  # footer
        self.assertContains(home, f'rel="icon" href="{favicon}"')

    def test_replace_and_remove(self):
        self.login(self.manager)
        self.upload("logo", PNG)
        self.upload("logo", PNG + b"\x00")
        self.assertEqual(BrandAsset.objects.count(), 1)
        self.assertEqual(BrandAsset.objects.get().size, len(PNG) + 1)
        self.client.post(reverse("core:branding"), {"kind": "logo", "action": "remove"})
        self.assertFalse(BrandAsset.objects.exists())
        self.assertEqual(self.client.get(reverse("brand_asset_public", args=["logo"])).status_code, 404)

    def test_rejects_non_images_and_large_files(self):
        self.login(self.manager)
        resp = self.upload("logo", b"<html><script>alert(1)</script></html>", "evil.png")
        self.assertContains(resp, "Upload a PNG")
        resp = self.upload("favicon", PNG + b"\x00" * (600 * 1024), "big.png")
        self.assertContains(resp, "too large")
        self.assertFalse(BrandAsset.objects.exists())

    def test_svg_is_sandboxed(self):
        self.login(self.manager)
        self.upload("logo", SVG, "logo.svg")
        resp = self.client.get(reverse("brand_asset_public", args=["logo"]))
        self.assertEqual(resp["Content-Type"], "image/svg+xml")
        self.assertIn("sandbox", resp["Content-Security-Policy"])
        self.assertIn("default-src 'none'", resp["Content-Security-Policy"])
        self.assertEqual(resp["X-Content-Type-Options"], "nosniff")

    def test_hide_name_beside_logo(self):
        self.login(self.manager)
        self.upload("logo", PNG)
        self.client.post(reverse("core:branding"), {"action": "identity", "hotel-name": "Hoteli Grand",
                                                    "hotel-tagline": "x"})
        self.client.logout()
        home = self.client.get("/").content.decode()
        nav = home.split('class="navbar-brand site-brand"')[1].split("</a>")[0]
        self.assertNotIn("<span>Hoteli", nav)

    def test_only_managers(self):
        self.login(self.reception)
        self.assertEqual(self.client.get(reverse("core:branding")).status_code, 403)
        self.assertEqual(self.upload("logo", PNG).status_code, 403)
        self.assertFalse(BrandAsset.objects.exists())


class HotelNameTests(HotelTestCase):
    def rename(self, **data):
        payload = {"action": "identity", "hotel-name": "Hoteli Grand", "hotel-tagline": "", "hotel-legal_name": "",
                   "hotel-logo_show_name": "on"}
        payload.update({f"hotel-{k}": v for k, v in data.items()})
        return self.client.post(reverse("core:branding"), payload)

    def test_manager_renames_hotel_and_it_shows_everywhere(self):
        self.login(self.manager)
        resp = self.rename(name="  Lakeview   Resort  ", tagline="Sunsets over Lake Naivasha")
        self.assertRedirects(resp, reverse("core:branding"))
        hotel = HotelSettings.load()
        self.assertEqual(hotel.name, "Lakeview Resort")  # extra spaces tidied
        self.assertTrue(AuditLog.objects.filter(action="settings.rename", description__contains="Lakeview").exists())
        self.assertContains(self.client.get(reverse("core:dashboard")), "Lakeview Resort")  # staff sidebar
        b = self.make_booking(ci=-1, co=1, status=Booking.Status.CHECKED_IN)
        self.assertContains(self.client.get(reverse("bookings:invoice", args=[b.pk])), "Lakeview Resort")
        p = record_payment(booking=b, amount=Decimal("100"), method=Payment.Method.CASH)
        self.assertContains(self.client.get(reverse("bookings:receipt", args=[p.pk])), "LAKEVIEW RESORT")
        self.client.logout()
        home = self.client.get("/")
        self.assertContains(home, "· Lakeview Resort</title>", html=False)
        self.assertContains(self.client.get(reverse("website:rooms")), "Sunsets over Lake Naivasha")  # tagline in footer
        self.assertContains(home, "&copy; 2026 Lakeview Resort".replace("2026", str(self.today.year)), html=False)
        self.assertContains(self.client.get(reverse("accounts:login")), "Lakeview Resort")

    def test_confirmation_email_uses_new_name(self):
        self.login(self.manager)
        self.rename(name="Lakeview Resort")
        b = self.make_booking(ci=1, co=2)
        self.assertTrue(send_booking_confirmation(b))
        self.assertIn("Lakeview Resort", mail.outbox[0].subject)
        self.assertTrue(mail.outbox[0].from_email.startswith("Lakeview Resort <"))
        self.assertIn("Lakeview Resort", mail.outbox[0].body)

    def test_registered_business_name_on_tax_documents(self):
        self.login(self.manager)
        self.rename(name="Lakeview Resort", legal_name="Naivasha Hospitality Ltd")
        b = self.make_booking(ci=-1, co=1, status=Booking.Status.CHECKED_IN)
        self.assertContains(self.client.get(reverse("bookings:invoice", args=[b.pk])), "Naivasha Hospitality Ltd")
        p = record_payment(booking=b, amount=Decimal("100"), method=Payment.Method.CASH)
        self.assertContains(self.client.get(reverse("bookings:receipt", args=[p.pk])), "Naivasha Hospitality Ltd")

    def test_blank_name_rejected(self):
        self.login(self.manager)
        resp = self.rename(name="   ")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["identity_form"].errors)
        self.assertEqual(HotelSettings.load().name, "Hoteli Grand")

    def test_logo_uploads_do_not_touch_the_name(self):
        self.login(self.manager)
        self.rename(name="Lakeview Resort")
        self.client.post(reverse("core:branding"), {
            "kind": "logo", "file": SimpleUploadedFile("logo.png", PNG, content_type="image/png"),
        })
        self.assertEqual(HotelSettings.load().name, "Lakeview Resort")
        self.assertTrue(BrandAsset.objects.filter(kind="logo").exists())

    def test_front_desk_cannot_rename(self):
        self.login(self.reception)
        self.assertEqual(self.rename(name="Hacked Hotel").status_code, 403)
        self.assertEqual(HotelSettings.load().name, "Hoteli Grand")


class StaticDemoExportTests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()

    def test_refuses_to_publish_a_real_database(self):
        from django.core.management import CommandError, call_command

        with self.assertRaisesMessage(CommandError, "Refusing to export"):
            call_command("export_static_demo", out="/tmp/never-written", stdout=__import__("io").StringIO())

    def test_exports_site_with_base_path(self):
        import io
        import json
        import tempfile
        from pathlib import Path

        from django.core.management import call_command
        from django.test import override_settings

        call_command("seed_demo", stdout=io.StringIO())
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEBUG=True, MPESA_SIMULATE=True):
            call_command("export_static_demo", out=tmp, base="/hoteli/", repo="pizzatechies/hoteli",
                         stdout=io.StringIO())
            out = Path(tmp)
            home = (out / "index.html").read_text()
            self.assertIn('href="/hoteli/static/css/site.css"', home)
            self.assertIn("hoteli-demo-bar", home)
            self.assertIn("https://codespaces.new/pizzatechies/hoteli", home)
            self.assertNotIn('href="/staff/', home)
            self.assertTrue((out / "staff" / "index.html").exists())
            self.assertTrue((out / "demo" / "index.html").exists())
            self.assertTrue((out / "404.html").exists())
            self.assertTrue((out / ".nojekyll").exists())
            manifest = (out / "static" / "js" / "demo-manifest.js").read_text()
            data = json.loads(manifest.split("=", 1)[1].strip().rstrip(";"))
            self.assertIn("/staff/bookings/", data["pages"])
            self.assertEqual(data["base"], "/hoteli/")


class LoginScreenTests(HotelTestCase):
    def test_login_shows_powered_by_pizza_technologies(self):
        resp = self.client.get(reverse("accounts:login"))
        self.assertContains(resp, 'Powered by <strong class="text-white">Pizza Technologies</strong>', html=False)
