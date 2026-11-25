import base64

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from core.branding import sniff_image
from core.models import BrandAsset
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
        self.client.post(reverse("core:branding"), {"action": "toggle_name"})
        self.client.logout()
        home = self.client.get("/").content.decode()
        nav = home.split('class="navbar-brand site-brand"')[1].split("</a>")[0]
        self.assertNotIn("<span>Hoteli", nav)

    def test_only_managers(self):
        self.login(self.reception)
        self.assertEqual(self.client.get(reverse("core:branding")).status_code, 403)
        self.assertEqual(self.upload("logo", PNG).status_code, 403)
        self.assertFalse(BrandAsset.objects.exists())
