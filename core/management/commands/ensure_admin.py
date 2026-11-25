import os

from django.core.management.base import BaseCommand

from accounts.models import User


class Command(BaseCommand):
    help = "Create the first administrator from DJANGO_ADMIN_USERNAME / DJANGO_ADMIN_PASSWORD if no admin exists."

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_ADMIN_USERNAME")
        password = os.environ.get("DJANGO_ADMIN_PASSWORD")
        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write("An administrator already exists; nothing to do.")
            return
        if not username or not password:
            self.stdout.write(self.style.WARNING(
                "Set DJANGO_ADMIN_USERNAME and DJANGO_ADMIN_PASSWORD to create the first administrator."
            ))
            return
        User.objects.create_superuser(
            username=username, password=password, email=os.environ.get("DJANGO_ADMIN_EMAIL", ""),
            role=User.Role.ADMIN, first_name="Admin",
        )
        self.stdout.write(self.style.SUCCESS(f"Administrator '{username}' created."))
