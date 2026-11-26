from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Staff user with a hotel role. Superusers are always treated as administrators."""

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrator"
        MANAGER = "MANAGER", "Manager"
        RECEPTIONIST = "RECEPTIONIST", "Front Desk"
        ACCOUNTANT = "ACCOUNTANT", "Accountant"
        HOUSEKEEPING = "HOUSEKEEPING", "Housekeeping"
        RESTAURANT = "RESTAURANT", "Restaurant / Bar"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.RECEPTIONIST)
    phone = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["first_name", "last_name", "username"]

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def effective_role(self):
        return self.Role.ADMIN if self.is_superuser else self.role

    @property
    def is_admin(self):
        return self.is_superuser or self.role == self.Role.ADMIN

    def has_role(self, *roles):
        """Administrators pass every role check."""
        if not self.is_authenticated or not self.is_active:
            return False
        return self.is_admin or self.role in roles

    def get_role_display_name(self):
        return self.Role(self.effective_role).label


class LoginAttempt(models.Model):
    """Every staff sign-in attempt, used to lock out password guessing."""

    username = models.CharField(max_length=150, db_index=True)
    ip_address = models.CharField(max_length=64, blank=True, db_index=True)
    successful = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.username} {'ok' if self.successful else 'failed'} {self.created_at:%Y-%m-%d %H:%M}"


class TwoFactorDevice(models.Model):
    """Authenticator-app (TOTP) second factor for a staff account."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="two_factor")
    secret = models.CharField(max_length=64)
    confirmed = models.BooleanField(default=False)
    last_used_step = models.BigIntegerField(default=0, help_text="Prevents re-using a code.")
    recovery_codes = models.JSONField(default=list, blank=True, help_text="SHA-256 hashes of unused codes.")
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"2FA for {self.user}"
