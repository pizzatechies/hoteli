from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.shortcuts import get_object_or_404, redirect, render

from core.models import log_action

from .forms import PasswordResetByAdminForm, StaffCreateForm, StaffEditForm
from .models import User
from .permissions import role_required


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for field in form.fields.values():
            field.widget.attrs["class"] = "form-control form-control-lg"
        return form


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
