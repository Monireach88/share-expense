import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_countries.fields import CountryField

from .currencies import CURRENCY_CHOICES, DEFAULT_CURRENCY


class Trip(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(_("trip name"), max_length=120)
    country = CountryField(_("country"), blank=True)
    start_date = models.DateField(_("start date"), null=True, blank=True)
    end_date = models.DateField(_("end date"), null=True, blank=True)
    base_currency = models.CharField(
        _("base currency"),
        max_length=3,
        choices=CURRENCY_CHOICES,
        default=DEFAULT_CURRENCY,
        help_text=_("All totals and balances are shown in this currency."),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date", "-created_at"]

    def __str__(self) -> str:
        return self.name

    def rate_map(self) -> dict:
        return {r.currency: r.rate for r in self.rates.all()}

    def currencies(self) -> list[str]:
        return [self.base_currency, *sorted(r.currency for r in self.rates.all())]


class TripMember(models.Model):
    """A user account that can open the trip. The owner manages it; members record expenses."""

    class Role(models.TextChoices):
        OWNER = "owner", _("Owner")
        MEMBER = "member", _("Member")

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["trip", "user"], name="unique_trip_member")]

    def __str__(self) -> str:
        return f"{self.user} ({self.role}) in {self.trip}"

    @property
    def is_owner(self) -> bool:
        return self.role == self.Role.OWNER


class Participant(models.Model):
    """A person who travels and shares costs. Needs no account; may be linked to one."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="participants")
    name = models.CharField(_("name"), max_length=80)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="participations",
        verbose_name=_("linked account"),
    )
    sponsors = models.ManyToManyField(
        "self",
        symmetrical=False,
        blank=True,
        related_name="sponsored",
        verbose_name=_("covered by"),
        help_text=_("People who pay this person's share. Leave empty if they pay for themselves."),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["trip", "name"], name="unique_participant_name")
        ]

    def __str__(self) -> str:
        return self.name


class ExchangeRate(models.Model):
    """Fixed rate for one trip: 1 unit of the base currency = ``rate`` units of ``currency``."""

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="rates")
    currency = models.CharField(_("currency"), max_length=3, choices=CURRENCY_CHOICES)
    rate = models.DecimalField(_("rate"), max_digits=18, decimal_places=6)

    class Meta:
        ordering = ["currency"]
        constraints = [
            models.UniqueConstraint(fields=["trip", "currency"], name="unique_trip_currency"),
            models.CheckConstraint(condition=models.Q(rate__gt=0), name="rate_positive"),
        ]

    def __str__(self) -> str:
        return f"1 {self.trip.base_currency} = {self.rate} {self.currency}"
