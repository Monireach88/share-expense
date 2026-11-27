from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from . import usernames


class User(AbstractUser):
    """A person who can log in. New sign-ups stay inactive until the admin approves them.

    The username is a-z, 0-9 and _ (3 to 30), always stored in lowercase, and unique in any
    letter case (a database index on the lowercase name backs this up).
    """

    username = models.CharField(
        "username",
        max_length=150,
        unique=True,
        validators=[usernames.validate_username],
        error_messages={"unique": usernames.TAKEN},
    )
    # The invite link this account came from while it waited for approval (spec section 6.3).
    # Its first sign-in opens that join page; opening any join page clears it.
    invite_token = models.CharField(max_length=64, blank=True, editable=False)

    class Meta(AbstractUser.Meta):
        constraints = [
            models.UniqueConstraint(
                Lower("username"),
                name="user_username_lower_unique",
                violation_error_message=usernames.TAKEN,
            )
        ]

    @property
    def display_name(self) -> str:
        return self.first_name or self.username

    def clean(self):
        super().clean()
        if not self.username:  # Already refused by the field's own checks.
            return
        self.username = self.username.strip().lower()
        clash = type(self).objects.filter(username=self.username).exclude(pk=self.pk)
        if clash.exists():
            raise ValidationError({"username": usernames.TAKEN}, code="unique")

    def save(self, *args, **kwargs):
        if self.username:
            self.username = self.username.lower()
        super().save(*args, **kwargs)
