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
