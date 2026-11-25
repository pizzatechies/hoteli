"""Role groups and access-control helpers used across the staff interface."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from .models import User

R = User.Role

# Who can do what. Administrators always pass.
FRONT_DESK = (R.MANAGER, R.RECEPTIONIST)
BOOKING_VIEW = (R.MANAGER, R.RECEPTIONIST, R.ACCOUNTANT)
FINANCE = (R.MANAGER, R.ACCOUNTANT)
CASHIERS = (R.MANAGER, R.RECEPTIONIST, R.ACCOUNTANT, R.RESTAURANT)
HOUSEKEEPING = (R.MANAGER, R.RECEPTIONIST, R.HOUSEKEEPING)
POS = (R.MANAGER, R.RECEPTIONIST, R.RESTAURANT)
MANAGEMENT = (R.MANAGER,)
REPORTS = (R.MANAGER, R.ACCOUNTANT)
ADMIN_ONLY = ()


def role_required(*roles):
    """Decorator: user must be logged in and hold one of ``roles`` (admins always pass)."""

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not request.user.has_role(*roles):
                raise PermissionDenied("You do not have access to this page.")
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


class RoleRequiredMixin(LoginRequiredMixin):
    allowed_roles = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.has_role(*self.allowed_roles):
            raise PermissionDenied("You do not have access to this page.")
        return super().dispatch(request, *args, **kwargs)
