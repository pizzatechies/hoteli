from django.contrib import messages
from django.shortcuts import redirect

from . import security

ALLOWED_PREFIXES = ("/staff/security/", "/staff/logout/", "/staff/login/", "/staff/manifest.webmanifest",
                    "/staff/sw.js", "/staff/offline/", "/static/", "/brand/", "/healthz/")


class TwoFactorEnforcementMiddleware:
    """When the hotel requires it, managers and admins must set up two-step login before continuing."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        path = request.path
        if (user is not None and user.is_authenticated and (path.startswith("/staff/") or path.startswith("/django-admin/"))
                and not path.startswith(ALLOWED_PREFIXES) and security.two_factor_required(user)):
            messages.warning(request, "Your hotel requires two-step login for managers. Set it up to continue.")
            return redirect("accounts:security")
        return self.get_response(request)
