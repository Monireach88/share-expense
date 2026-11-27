"""Disputes about one expense, their messages, and the in-app notifications (spec sections 4, 5).

The rules (who may open, write, resolve, close, and who is notified) live in ``rules.py``.
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.expenses.models import Expense
from apps.trips.models import Trip


class Dispute(models.Model):
    """A complaint about one expense, by a traveler who disagrees with it.

    Open until the opener taps Resolved or the Owner closes it with a reason; it never reopens.
    """

    class State(models.TextChoices):
        OPEN = "open", _("Open")
        RESOLVED = "resolved", _("Resolved")
        CLOSED = "closed", _("Closed")

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="disputes")
    # RESTRICT: an expense with a dispute cannot be erased on its own (removing its payer is
    # refused first), but deleting the whole trip removes both together.
    expense = models.ForeignKey(Expense, on_delete=models.RESTRICT, related_name="disputes")
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    opened_by_name = models.CharField(max_length=150)
    # The opener's linked traveler when the dispute was opened, so the heading still reads
    # "Dispute by Friend (Person B)" after an unlink or rename.
    opened_as = models.CharField(max_length=80, blank=True)
    reason = models.TextField(_("reason"), max_length=500)
    state = models.CharField(max_length=10, choices=State.choices, default=State.OPEN)
    close_reason = models.TextField(_("reason for closing"), max_length=500, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    closed_by_name = models.CharField(max_length=150, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["expense", "opened_by"],
                condition=models.Q(state="open"),
                name="one_open_dispute_per_account",
            )
        ]

    def __str__(self) -> str:
        return f"{self.opened_by_name} on {self.expense_id} ({self.state})"

    @property
    def is_open(self) -> bool:
        return self.state == self.State.OPEN

    @property
    def opener_label(self) -> str:
        """ "Friend (Person B)"; the name once when account and traveler share it."""
        if not self.opened_as or self.opened_as == self.opened_by_name:
            return self.opened_by_name
        return f"{self.opened_by_name} ({self.opened_as})"


class DisputeMessage(models.Model):
    dispute = models.ForeignKey(Dispute, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    author_name = models.CharField(max_length=150)
    text = models.TextField(_("message"), max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"{self.author_name}: {self.text[:40]}"


class NotificationQuerySet(models.QuerySet):
    def visible_to(self, user):
        """The account's items, without those of trips it is no longer on (spec section 4)."""
        return self.filter(user=user, trip__memberships__user=user)


class Notification(models.Model):
    """One item in an account's in-app list. The app sends no email or push message.

    Stores names and text, not live rows, so it reads the same after a rename; ``link`` is the
    address it opens (an expense page, or the History entry of a settle or reopen).
    """

    class Kind(models.TextChoices):
        DISPUTE_OPENED = "dispute_opened"
        DISPUTE_MESSAGE = "dispute_message"
        DISPUTE_RESOLVED = "dispute_resolved"
        DISPUTE_CLOSED = "dispute_closed"
        SETTLED = "settled"
        REOPENED = "reopened"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    actor_name = models.CharField(max_length=150)
    label = models.CharField(max_length=200, blank=True)
    detail = models.CharField(max_length=200, blank=True)
    opener_name = models.CharField(max_length=150, blank=True)  # For "closed Cara’s dispute".
    link = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    objects = NotificationQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["user", "-created_at"], name="notification_user_time")]

    def __str__(self) -> str:
        return f"{self.user} {self.kind} {self.label}"
