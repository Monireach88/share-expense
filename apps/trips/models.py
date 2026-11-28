import uuid

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy
from django_countries.fields import CountryField

from .currencies import CURRENCY_CHOICES, DEFAULT_CURRENCY


class Trip(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(_("trip name"), max_length=120)
    # English copy of the name when it has Khmer or Chinese letters (apps/trips/english.py).
    name_en = models.CharField(_("trip name in English"), max_length=120, blank=True)
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
    # Set when the owner marks the trip as settled; the expenses are then locked until the
    # owner reopens it. How people paid each other is up to them, not recorded here.
    settled_at = models.DateTimeField(_("settled on"), null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date", "-created_at"]

    def __str__(self) -> str:
        return self.name

    @property
    def is_settled(self) -> bool:
        return self.settled_at is not None

    def rate_map(self) -> dict:
        return {r.currency: r.rate for r in self.rates.all()}

    def currencies(self) -> list[str]:
        return [self.base_currency, *sorted(r.currency for r in self.rates.all())]


class TripMember(models.Model):
    """A user account that can open the trip, with one role.

    Owner: everything, including travelers, accounts, rates and settings. Exactly one per trip.
    Editor: every expense and type, settling and reopening.
    Member: only expenses their linked traveler paid. A Member with no linked traveler is shown
    as "Viewer" and can only look. The checks below are the one place these rules live.
    """

    class Role(models.TextChoices):
        OWNER = "owner", pgettext_lazy("trip role", "Owner")
        EDITOR = "editor", pgettext_lazy("trip role", "Editor")
        MEMBER = "member", pgettext_lazy("trip role", "Member")

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["trip", "user"], name="unique_trip_member"),
            models.UniqueConstraint(
                fields=["trip"], condition=models.Q(role="owner"), name="one_owner_per_trip"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} ({self.role}) in {self.trip}"

    @property
    def is_owner(self) -> bool:
        return self.role == self.Role.OWNER

    @property
    def is_editor(self) -> bool:
        return self.role == self.Role.EDITOR

    @cached_property
    def linked_traveler(self) -> Participant | None:
        """The one traveler of this trip linked to this account, or None."""
        return self.trip.participants.filter(user_id=self.user_id).first()

    @property
    def is_viewer(self) -> bool:
        """A Member with no linked traveler: may look at everything but change nothing."""
        return self.role == self.Role.MEMBER and self.linked_traveler is None

    @property
    def role_label(self) -> str:
        return pgettext_lazy("trip role", "Viewer") if self.is_viewer else self.get_role_display()

    @property
    def can_manage_expenses(self) -> bool:
        """Any payer, any expense, rename or remove types, reorder, settle and reopen."""
        return self.role in (self.Role.OWNER, self.Role.EDITOR)

    @property
    def can_add_expense(self) -> bool:
        """Also covers adding a type, Add with AI and the description suggestion."""
        return self.can_manage_expenses or self.linked_traveler is not None

    @property
    def can_settle(self) -> bool:
        return self.can_manage_expenses

    def can_edit_expense(self, expense) -> bool:
        """Edit, delete or restore: Owner and Editors any expense, a Member only their own."""
        if self.can_manage_expenses:
            return True
        traveler = self.linked_traveler
        return traveler is not None and expense.payer_id == traveler.pk

    def allowed_payer(self, payer_id) -> bool:
        """A Member may record only their own traveler as payer; Owner and Editors anyone."""
        if self.can_manage_expenses:
            return True
        traveler = self.linked_traveler
        return traveler is not None and str(payer_id) == str(traveler.pk)


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
            models.UniqueConstraint(fields=["trip", "name"], name="unique_participant_name"),
            models.UniqueConstraint(
                fields=["trip", "user"],
                condition=models.Q(user__isnull=False),
                name="one_traveler_per_account",
            ),
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


class HistoryQuerySet(models.QuerySet):
    """History is append-only: nothing in the code updates or deletes entries.

    Deleting a whole trip still removes its entries, because Django's cascade does not go
    through these methods.
    """

    def update(self, **kwargs):
        raise TypeError("History entries cannot be changed.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise TypeError("History entries cannot be changed.")

    def delete(self):
        raise TypeError("History entries cannot be deleted.")


class HistoryEntry(models.Model):
    """One change to a trip, written in the same transaction as the change (``history.record``).

    Values are kept as names and text, plus ids, so an entry still reads correctly after a
    traveler, type or account is renamed or removed.
    """

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="history")
    created_at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    actor_name = models.CharField(max_length=150)
    action = models.CharField(max_length=30)
    object_type = models.CharField(max_length=20)
    object_id = models.CharField(max_length=40, blank=True)
    object_label = models.CharField(max_length=200, blank=True)
    # Per changed field: {"amount": {"old": "40 USD", "new": "4 USD"}}, plus ids where useful.
    changes = models.JSONField(default=dict)
    # An expense's full values after the action; Restore brings back the last ones.
    values = models.JSONField(default=dict)
    # Lowercase text built at write time, so the History search runs in the database.
    search_text = models.TextField(blank=True)

    objects = HistoryQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["trip", "-created_at"], name="history_trip_time")]
        verbose_name_plural = _("history entries")

    def __str__(self) -> str:
        return f"{self.actor_name} {self.action} {self.object_type} {self.object_label}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("History entries cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("History entries cannot be deleted.")


class Invite(models.Model):
    """A personal invite: one email address, one trip, one traveler choice (spec section 6.2).

    The link holds a random token; only its SHA-256 hash is stored, so a new link (Copy link,
    Send again) replaces the hash and ends the old link. An invite is open while it is pending
    or expired; Send again makes an expired one pending again. The database allows one open
    invite per trip and address, letter case ignored.
    """

    class State(models.TextChoices):
        PENDING = "pending", pgettext_lazy("invite state", "Pending")
        EXPIRED = "expired", pgettext_lazy("invite state", "Expired")
        ACCEPTED = "accepted", pgettext_lazy("invite state", "Accepted")
        CANCELLED = "cancelled", pgettext_lazy("invite state", "Cancelled")

    OPEN_STATES = (State.PENDING, State.EXPIRED)

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="invites")
    email = models.EmailField(_("email address"))
    # The traveler choice: an existing traveler, a new traveler's name, or neither (view only).
    traveler = models.ForeignKey(
        Participant, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    traveler_name = models.CharField(max_length=80, blank=True)  # Kept if the traveler goes.
    new_traveler_name = models.CharField(max_length=80, blank=True)
    token_hash = models.CharField(max_length=64, unique=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.PENDING)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    invited_by_name = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                "trip",
                condition=models.Q(state__in=["pending", "expired"]),
                name="one_open_invite_per_address",
            )
        ]

    def __str__(self) -> str:
        return f"{self.email} to {self.trip} ({self.state})"

    @property
    def is_open(self) -> bool:
        return self.state in self.OPEN_STATES

    @property
    def traveler_label(self) -> str:
        """The traveler the invite is for, or "" for view only."""
        return self.new_traveler_name or self.traveler_name


class InviteEmailAttempt(models.Model):
    """One invite email sent or attempted, counted for the limit of 20 per account per hour."""

    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["sender", "created_at"], name="invite_email_sender_time")]

    def __str__(self) -> str:
        return f"{self.sender} at {self.created_at}"
