import time

from django.test import override_settings
from django.urls import reverse

from accounts import security
from accounts.models import LoginAttempt, TwoFactorDevice
from core.models import HotelSettings
from hoteli.testutils import HotelTestCase


def current_code(device, offset=0):
    return security.totp(device.secret, security.current_step() + offset)


class TotpTests(HotelTestCase):
    def test_rfc6238_reference_vector(self):
        # RFC 6238 test secret "12345678901234567890" (base32) at T=59s -> 94287082 (8 digits) -> ...287082
        secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
        self.assertEqual(security.totp(secret, 59 // 30), "287082")

    def test_code_cannot_be_reused(self):
        device = TwoFactorDevice.objects.create(user=self.manager, secret=security.new_secret(), confirmed=True)
        code = current_code(device)
        self.assertTrue(security.verify_code(device, code))
        self.assertFalse(security.verify_code(device, code))

    def test_recovery_codes_work_once(self):
        device = TwoFactorDevice.objects.create(user=self.manager, secret=security.new_secret(), confirmed=True)
        codes = security.make_recovery_codes(device)
        self.assertEqual(len(codes), 8)
        self.assertTrue(security.use_recovery_code(device, codes[0].lower()))
        self.assertFalse(security.use_recovery_code(device, codes[0]))
        self.assertEqual(len(device.recovery_codes), 7)


class LockoutTests(HotelTestCase):
    def attempt(self, password, username="frontdesk"):
        return self.client.post(reverse("accounts:login"), {"username": username, "password": password})

    @override_settings(LOGIN_LOCKOUT_ATTEMPTS=3)
    def test_account_locks_after_repeated_failures(self):
        for _ in range(3):
            self.assertContains(self.attempt("wrong"), "Incorrect username or password")
        resp = self.attempt(self.password)  # correct password, but locked
        self.assertContains(resp, "locked for about")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_successful_login_clears_failures(self):
        self.attempt("wrong")
        resp = self.attempt(self.password)
        self.assertRedirects(resp, reverse("core:dashboard"), fetch_redirect_response=False)
        self.assertFalse(LoginAttempt.objects.filter(username="frontdesk", successful=False).exists())


class TwoFactorFlowTests(HotelTestCase):
    def enable(self, user):
        self.login(user)
        self.client.get(reverse("accounts:security"))
        device = TwoFactorDevice.objects.get(user=user)
        resp = self.client.post(reverse("accounts:security"), {"action": "confirm", "code": current_code(device)})
        self.assertContains(resp, "recovery codes")
        self.client.logout()
        device.refresh_from_db()
        device.last_used_step = 0
        device.save()
        return device

    def test_setup_then_login_requires_code(self):
        device = self.enable(self.manager)
        resp = self.client.post(reverse("accounts:login"), {"username": "manager", "password": self.password})
        self.assertRedirects(resp, reverse("accounts:login_verify"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(self.client.post(reverse("accounts:login_verify"), {"code": "000000"}), "Check your authenticator app")
        resp = self.client.post(reverse("accounts:login_verify"), {"code": current_code(device)})
        self.assertRedirects(resp, reverse("core:dashboard"), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.manager.pk)

    def test_recovery_code_login(self):
        device = self.enable(self.manager)
        codes = security.make_recovery_codes(device)
        self.client.post(reverse("accounts:login"), {"username": "manager", "password": self.password})
        resp = self.client.post(reverse("accounts:login_verify"), {"code": codes[3]})
        self.assertRedirects(resp, reverse("core:dashboard"), fetch_redirect_response=False)

    def test_pending_step_expires(self):
        self.enable(self.manager)
        self.client.post(reverse("accounts:login"), {"username": "manager", "password": self.password})
        session = self.client.session
        session["two_factor_pending"]["ts"] = time.time() - 600
        session.save()
        self.assertRedirects(self.client.get(reverse("accounts:login_verify")), reverse("accounts:login"))

    def test_hotel_can_require_two_factor_for_managers(self):
        hotel = HotelSettings.objects.get_or_create(pk=1)[0]
        hotel.require_two_factor_for_managers = True
        hotel.save()
        self.login(self.manager)
        self.assertRedirects(self.client.get(reverse("bookings:list")), reverse("accounts:security"))
        self.login(self.reception)  # front desk is not forced
        self.assertEqual(self.client.get(reverse("bookings:list")).status_code, 200)

    def test_admin_can_reset_lost_phone(self):
        self.enable(self.manager)
        self.login(self.admin)
        self.client.post(reverse("accounts:user_reset_two_factor", args=[self.manager.pk]))
        self.assertFalse(TwoFactorDevice.objects.filter(user=self.manager).exists())

    def test_django_admin_login_goes_through_staff_login(self):
        resp = self.client.get("/django-admin/login/?next=/django-admin/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith(reverse("accounts:login")))
