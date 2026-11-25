"""Render the hotel website and staff screens to static HTML for a GitHub Pages demo.

Intended for CI with a throwaway demo database:

    python manage.py migrate && python manage.py seed_demo
    python manage.py export_static_demo --out _site --base /hoteli/ --repo owner/hoteli

Every page is rendered through Django exactly as users see it, then its internal links are
rewritten for the sub-path GitHub Pages serves the site from. A small script adds a demo banner
and explains that forms (bookings, payments, staff actions) need the live demo.
"""

import datetime
import json
import re
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.template.loader import render_to_string
from django.test import Client
from django.utils import timezone

from accounts.models import User
from bookings.models import Booking, Guest, Payment
from housekeeping.models import MaintenanceRequest
from mpesa.models import MpesaTransaction
from pos.models import Order
from rooms.models import Room, RoomType
from website.models import Page

ATTR_RE = re.compile(r'(\s(?:href|src|action|data-[a-z-]+)=)(["\'])/(?!/)')
CSS_URL_RE = re.compile(r"url\((['\"]?)/(?!/)")
BODY_RE = re.compile(r"(<body[^>]*>)", re.IGNORECASE)


class Command(BaseCommand):
    help = "Export a static, browsable demo of the website and staff screens (for GitHub Pages)."

    def add_arguments(self, parser):
        parser.add_argument("--out", default="_site", help="Output directory (will be replaced).")
        parser.add_argument("--base", default="/", help="URL path the site is served from, e.g. /hoteli/")
        parser.add_argument("--repo", default="", help="GitHub owner/name, used for the live-demo links.")
        parser.add_argument("--site-url", default="", help="Public URL of the static site.")
        parser.add_argument("--force", action="store_true",
                            help="Export even if this does not look like a demo database (publishes its data!).")

    # ------------------------------------------------------------------ entry point
    def handle(self, *args, **opts):
        engine = settings.DATABASES["default"]["ENGINE"]
        looks_like_demo = settings.DEBUG and settings.MPESA_SIMULATE and "sqlite" in engine
        if not looks_like_demo and not opts["force"]:
            raise CommandError(
                "Refusing to export: this would publish the database's guest data. Run it against a fresh "
                "demo database (DEBUG=True, SQLite, M-Pesa simulation) or pass --force."
            )
        if not User.objects.filter(username="admin").exists():
            raise CommandError("No demo data found. Run `python manage.py seed_demo` first.")

        base = "/" + opts["base"].strip("/") + "/" if opts["base"].strip("/") else "/"
        repo = opts["repo"].strip("/")
        owner, _, name = repo.partition("/")
        site_url = opts["site_url"] or (f"https://{owner.lower()}.github.io/{name}/" if repo else "")
        self.base, self.repo, self.site_url = base, repo, site_url.rstrip("/") + "/" if site_url else ""
        self.live_url = f"https://codespaces.new/{repo}?quickstart=1" if repo else ""
        self.repo_url = f"https://github.com/{repo}" if repo else ""

        out = Path(opts["out"]).resolve()
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        self.out = out

        public = Client(HTTP_HOST="localhost")
        staff = Client(HTTP_HOST="localhost")
        staff.force_login(User.objects.get(username="admin"))

        pages = {}
        for path, url in self.public_urls():
            pages[path] = (public, url)
        pages["/staff/login/"] = (public, "/staff/login/")
        for path, url in self.staff_urls():
            pages[path] = (staff, url)

        exported = []
        for path, (client, url) in pages.items():
            resp = client.get(url)
            if resp.status_code != 200 or "text/html" not in resp.get("Content-Type", ""):
                self.stdout.write(self.style.WARNING(f"skip {url} ({resp.status_code})"))
                continue
            self.write(path, resp.content.decode("utf-8"))
            exported.append(path)

        self.write("/demo/", render_to_string("demo/index.html", self.demo_context()), rewrite_only=True)
        exported.append("/demo/")
        self.write_404()
        self.copy_static()
        self.write_manifest(exported)
        (out / ".nojekyll").write_text("")
        self.stdout.write(self.style.SUCCESS(f"Exported {len(exported)} pages to {out} (base {base})."))

    # ------------------------------------------------------------------ what to export
    def demo_dates(self):
        ci = timezone.localdate() + datetime.timedelta(days=7)
        return ci, ci + datetime.timedelta(days=3)

    def public_urls(self):
        ci, co = self.demo_dates()
        q = f"?check_in={ci}&check_out={co}&adults=2&children=0"
        yield "/", "/"
        for path in ["/rooms/", "/dining/", "/facilities/", "/contact/", "/booking/find/"]:
            yield path, path
        for rt in RoomType.objects.filter(is_active=True):
            yield f"/rooms/{rt.pk}/", f"/rooms/{rt.pk}/"
            yield f"/book/{rt.pk}/", f"/book/{rt.pk}/{q}"
        yield "/book/", f"/book/{q}"
        for page in Page.objects.filter(is_published=True, is_home=False):
            yield f"/p/{page.slug}/", f"/p/{page.slug}/"
        for b in Booking.objects.exclude(status=Booking.Status.CANCELLED):
            yield f"/booking/{b.public_token}/", f"/booking/{b.public_token}/"

    def staff_urls(self):
        simple = [
            "/staff/", "/staff/frontdesk/", "/staff/frontdesk/guest-register/", "/staff/calendar/", "/staff/bookings/",
            "/staff/bookings/new/", "/staff/guests/", "/staff/guests/new/", "/staff/payments/", "/staff/rooms/",
            "/staff/rooms/types/", "/staff/housekeeping/", "/staff/housekeeping/tasks/",
            "/staff/housekeeping/maintenance/", "/staff/housekeeping/maintenance/new/", "/staff/pos/",
            "/staff/pos/orders/", "/staff/pos/menu/", "/staff/mpesa/", "/staff/mpesa/paybill/",
            "/staff/mpesa/callbacks/", "/staff/reports/", "/staff/settings/", "/staff/branding/",
            "/staff/audit-log/", "/staff/users/", "/staff/inbox/", "/staff/website/", "/staff/website/builder/",
        ]
        simple += [
            "/staff/password/", "/staff/rooms/new/", "/staff/rooms/types/new/", "/staff/rooms/rates/new/",
            "/staff/housekeeping/tasks/new/", "/staff/pos/menu/items/new/", "/staff/pos/menu/categories/new/",
            "/staff/users/new/", "/staff/website/facilities/new/",
        ]
        for path in simple:
            yield path, path
        for b in Booking.objects.all():
            yield f"/staff/bookings/{b.pk}/", f"/staff/bookings/{b.pk}/"
            yield f"/staff/bookings/{b.pk}/invoice/", f"/staff/bookings/{b.pk}/invoice/"
            if b.can_edit:
                yield f"/staff/bookings/{b.pk}/edit/", f"/staff/bookings/{b.pk}/edit/"
        for g in Guest.objects.all():
            yield f"/staff/guests/{g.pk}/", f"/staff/guests/{g.pk}/"
            yield f"/staff/guests/{g.pk}/edit/", f"/staff/guests/{g.pk}/edit/"
        from housekeeping.models import HousekeepingTask
        from pos.models import MenuCategory, MenuItem
        from rooms.models import SeasonalRate
        from website.models import Facility

        for model, pattern in [
            (Room, "/staff/rooms/{}/edit/"), (RoomType, "/staff/rooms/types/{}/edit/"),
            (SeasonalRate, "/staff/rooms/rates/{}/edit/"), (MenuItem, "/staff/pos/menu/items/{}/edit/"),
            (MenuCategory, "/staff/pos/menu/categories/{}/edit/"), (User, "/staff/users/{}/"),
            (Facility, "/staff/website/facilities/{}/"), (HousekeepingTask, "/staff/housekeeping/tasks/{}/edit/"),
        ]:
            for pk in model.objects.values_list("pk", flat=True):
                yield pattern.format(pk), pattern.format(pk)
        for p in Payment.objects.all():
            yield f"/staff/payments/{p.pk}/receipt/", f"/staff/payments/{p.pk}/receipt/"
        for o in Order.objects.all():
            yield f"/staff/pos/orders/{o.pk}/", f"/staff/pos/orders/{o.pk}/"
            yield f"/staff/pos/orders/{o.pk}/bill/", f"/staff/pos/orders/{o.pk}/bill/"
        for tx in MpesaTransaction.objects.all():
            yield f"/staff/mpesa/{tx.pk}/", f"/staff/mpesa/{tx.pk}/"
        for page in Page.objects.all():
            yield f"/staff/website/builder/pages/{page.pk}/", f"/staff/website/builder/pages/{page.pk}/"
            for section in page.sections.all():
                yield f"/staff/website/builder/sections/{section.pk}/", f"/staff/website/builder/sections/{section.pk}/"
            if not page.is_published or page.is_home:
                yield f"/p/{page.slug}/", f"/p/{page.slug}/?preview=1"
        for m in MaintenanceRequest.objects.all():
            yield f"/staff/housekeeping/maintenance/{m.pk}/", f"/staff/housekeeping/maintenance/{m.pk}/"

    # ------------------------------------------------------------------ writing
    def rewrite(self, html):
        base = self.base
        if base != "/":
            html = ATTR_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{base}", html)
            html = CSS_URL_RE.sub(lambda m: f"url({m.group(1)}{base}", html)
        if self.site_url:
            html = html.replace("http://localhost/", self.site_url)
        return html

    def inject(self, html):
        banner = render_to_string("demo/_banner.html", {
            "base": self.base, "live_url": self.live_url, "repo_url": self.repo_url,
        })
        scripts = (f'<script src="{self.base}static/js/demo-manifest.js"></script>'
                   f'<script src="{self.base}static/js/static-demo.js"></script>')
        html = BODY_RE.sub(lambda m: m.group(1) + banner, html, count=1)
        return html.replace("</body>", scripts + "</body>", 1) if "</body>" in html else html + scripts

    def write(self, path, html, rewrite_only=False):
        target = self.out / path.strip("/") / "index.html" if path.strip("/") else self.out / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        html = self.rewrite(html)
        if not rewrite_only:
            html = self.inject(html)
        target.write_text(html, encoding="utf-8")

    def write_404(self):
        html = render_to_string("demo/404.html", self.demo_context())
        (self.out / "404.html").write_text(self.rewrite(html), encoding="utf-8")

    def copy_static(self):
        for source in settings.STATICFILES_DIRS:
            shutil.copytree(source, self.out / "static", dirs_exist_ok=True)

    def write_manifest(self, paths):
        data = {"base": self.base, "pages": sorted(set(paths)), "live": self.live_url, "repo": self.repo_url,
                "staff": f"{self.base}staff/", "book": f"{self.base}book/"}
        target = self.out / "static" / "js" / "demo-manifest.js"
        target.write_text("window.HOTELI_DEMO = " + json.dumps(data) + ";\n", encoding="utf-8")

    def demo_context(self):
        from core.models import HotelSettings

        ci, co = self.demo_dates()
        return {
            "base": self.base, "live_url": self.live_url, "repo_url": self.repo_url, "hotel": HotelSettings.load(),
            "first_booking": Booking.objects.filter(status=Booking.Status.CHECKED_IN).first(),
            "order": Order.objects.first(), "generated": timezone.localtime(), "check_in": ci, "check_out": co,
            "logins": ["admin", "manager", "reception", "accounts", "housekeeping", "restaurant"],
        }
