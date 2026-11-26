import time

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.models import HotelSettings, log_action

from . import security
from .forms import PasswordResetByAdminForm, StaffCreateForm, StaffEditForm
from .models import LoginAttempt, TwoFactorDevice, User
from .permissions import role_required

PENDING_KEY = "two_factor_pending"
PENDING_SECONDS = 300


class LoginView(auth_views.LoginView):
    """Password login with lockout; hands over to the code step for accounts with two-step login."""

    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for field in form.fields.values():
            field.widget.attrs["class"] = "form-control form-control-lg"
        return form

    def post(self, request, *args, **kwargs):
        username = request.POST.get("username", "").strip()
        minutes = security.lockout_status(username, security.client_ip(request))
        if minutes:
            form = self.get_form_class()(request=request)  # unbound: don't even try the password
            for field in form.fields.values():
                field.widget.attrs["class"] = "form-control form-control-lg"
            log_action(None, "security.lockout", None, f"Blocked sign-in for '{username[:40]}' (too many failures)")
            return self.render_to_response(self.get_context_data(
                form=form, locked_minutes=minutes,
            ))
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        security.record_attempt(self.request.POST.get("username", "").strip(), security.client_ip(self.request), False)
        return super().form_invalid(form)

    def form_valid(self, form):
        user = form.get_user()
        ip = security.client_ip(self.request)
        security.record_attempt(user.username, ip, True)
        if security.has_two_factor(user):
            self.request.session[PENDING_KEY] = {
                "uid": user.pk, "backend": user.backend, "ts": time.time(),
                "next": self.get_redirect_url() or "",
            }
            return redirect("accounts:login_verify")
        return super().form_valid(form)


def login_verify(request):
    """Second step: a code from the authenticator app, or a one-time recovery code."""
    pending = request.session.get(PENDING_KEY)
    if not pending or time.time() - pending.get("ts", 0) > PENDING_SECONDS:
        request.session.pop(PENDING_KEY, None)
        messages.error(request, "Please sign in again.")
        return redirect("accounts:login")
    user = User.objects.filter(pk=pending["uid"], is_active=True).select_related("two_factor").first()
    if user is None or not security.has_two_factor(user):
        request.session.pop(PENDING_KEY, None)
        return redirect("accounts:login")
    error = ""
    if request.method == "POST":
        ip = security.client_ip(request)
        if security.lockout_status(user.username, ip):
            request.session.pop(PENDING_KEY, None)
            messages.error(request, "Too many attempts. Please wait and sign in again.")
            return redirect("accounts:login")
        code = request.POST.get("code", "")
        device = user.two_factor
        used_recovery = False
        ok = security.verify_code(device, code)
        if not ok and len(code.strip()) >= 8:
            ok = used_recovery = security.use_recovery_code(device, code)
        if ok:
            nxt = pending.get("next") or ""
            request.session.pop(PENDING_KEY, None)
            user.backend = pending["backend"]
            auth_login(request, user)
            if used_recovery:
                messages.warning(request, f"Recovery code used. {len(device.recovery_codes)} left – make new ones "
                                          "under Account security.")
                log_action(user, "security.recovery_code", user, "Signed in with a recovery code")
            if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()},
                                                       require_https=request.is_secure()):
                return redirect(nxt)
            return redirect("core:dashboard")
        security.record_attempt(user.username, ip, False)
        error = "That code didn't work. Check your authenticator app and try again."
    return render(request, "accounts/login_verify.html", {"error": error, "staff_user": user})


@login_required
def account_security(request):
    """Set up, check or remove two-step login for the signed-in user."""
    user = request.user
    device, _ = TwoFactorDevice.objects.get_or_create(user=user, defaults={"secret": security.new_secret()})
    recovery_codes = None
    error = ""
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "confirm" and not device.confirmed:
            if security.verify_code(device, request.POST.get("code", "")):
                device.confirmed = True
                device.confirmed_at = timezone.now()
                device.save(update_fields=["confirmed", "confirmed_at"])
                recovery_codes = security.make_recovery_codes(device)
                log_action(user, "security.2fa_on", user, f"{user.username} turned on two-step login")
                messages.success(request, "Two-step login is on. Save your recovery codes now.")
            else:
                error = "That code didn't match. Make sure your phone's clock is correct and try again."
        elif action == "regenerate" and device.confirmed:
            recovery_codes = security.make_recovery_codes(device)
            messages.success(request, "New recovery codes created. The old ones no longer work.")
        elif action == "disable" and device.confirmed:
            if security.verify_code(device, request.POST.get("code", "")):
                device.delete()
                log_action(user, "security.2fa_off", user, f"{user.username} turned off two-step login")
                messages.success(request, "Two-step login is off.")
                return redirect("accounts:security")
            error = "Enter a current code from your authenticator app to turn two-step login off."
    hotel = HotelSettings.load()
    return render(request, "accounts/security.html", {
        "device": device, "recovery_codes": recovery_codes, "error": error,
        "otp_uri": security.provisioning_uri(device, hotel.name), "required": security.two_factor_required(user),
        "recent_attempts": LoginAttempt.objects.filter(username__iexact=user.username)[:8],
    })


@role_required()
@require_POST
def user_reset_two_factor(request, pk):
    staff = get_object_or_404(User, pk=pk)
    TwoFactorDevice.objects.filter(user=staff).delete()
    log_action(request.user, "security.2fa_reset", staff, f"Reset two-step login for {staff.username}")
    messages.success(request, f"Two-step login reset for {staff.username}. They can set it up again at next sign-in.")
    return redirect("accounts:user_edit", pk=pk)


def admin_login_redirect(request, extra_context=None):
    """Send the Django admin's own login through the staff login (lockout + two-step login)."""
    from django.urls import reverse

    nxt = request.get_full_path()
    return redirect(f"{reverse('accounts:login')}?next={request.GET.get('next', nxt)}")


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = "/staff/"

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for field in form.fields.values():
            field.widget.attrs["class"] = "form-control"
        return form

    def form_valid(self, form):
        messages.success(self.request, "Your password has been changed.")
        return super().form_valid(form)


@role_required()
def user_list(request):
    return render(request, "accounts/user_list.html", {"users": User.objects.all().order_by("-is_active", "role")})


@role_required()
def user_create(request):
    form = StaffCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        log_action(request.user, "user.create", user, f"Created staff account {user.username} ({user.role})")
        messages.success(request, f"Account {user.username} created.")
        return redirect("accounts:users")
    return render(request, "accounts/user_form.html", {"form": form, "title": "Add staff member"})


@role_required()
def user_edit(request, pk):
    staff = get_object_or_404(User, pk=pk)
    setting_password = request.method == "POST" and "set_password" in request.POST
    form = StaffEditForm(None if setting_password else (request.POST or None), instance=staff)
    pw_form = PasswordResetByAdminForm(request.POST if setting_password else None, prefix="pw")
    if request.method == "POST":
        if setting_password:
            if pw_form.is_valid():
                staff.set_password(pw_form.cleaned_data["new_password"])
                staff.save()
                log_action(request.user, "user.password", staff, f"Reset password for {staff.username}")
                messages.success(request, f"Password for {staff.username} updated.")
                return redirect("accounts:users")
        elif form.is_valid():
            if staff == request.user and not form.cleaned_data["is_active"]:
                messages.error(request, "You cannot deactivate your own account.")
            else:
                form.save()
                log_action(request.user, "user.update", staff, f"Updated {staff.username} ({staff.role})")
                messages.success(request, "Staff member updated.")
                return redirect("accounts:users")
    return render(request, "accounts/user_form.html", {
        "form": form, "pw_form": pw_form, "title": f"Edit {staff}", "staff": staff,
    })
