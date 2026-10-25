from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """A person who can log in. New sign-ups stay inactive until the admin approves them."""

    @property
    def display_name(self) -> str:
        return self.first_name or self.username
