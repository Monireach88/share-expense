from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy

from . import usernames


class Appearance(models.TextChoices):
    SYSTEM = "system", gettext_lazy("System")
    LIGHT = "light", gettext_lazy("Light")
    DARK = "dark", gettext_lazy("Dark")


class User(AbstractUser):
    """A person who can log in. Inactive accounts either wait for the admin's approval (made
    before personal invites existed) or were closed by their owner (``closed_at`` is set).

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
    # Set when the person closes their account (spec section 6.5). A closed account is also
    # inactive; this field tells it apart from one that waits for the admin's approval.
    closed_at = models.DateTimeField("closed on", null=True, blank=True)

    # The colour scheme the person chose in the account menu; "system" follows the device.
    appearance = models.CharField(
        "appearance", max_length=6, choices=Appearance.choices, default=Appearance.SYSTEM
    )

    class Meta(AbstractUser.Meta):
        constraints = [
            models.UniqueConstraint(
                Lower("username"),
                name="user_username_lower_unique",
                violation_error_message=usernames.TAKEN,
            )
        ]

    @property
    def is_closed(self) -> bool:
        return self.closed_at is not None

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
