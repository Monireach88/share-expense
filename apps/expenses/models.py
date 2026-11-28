import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy

from apps.trips import english
from apps.trips.currencies import CURRENCY_CHOICES
from apps.trips.models import Participant, Trip

# The types every new trip starts with: (name, emoji). Travelers can add, rename and remove types.
DEFAULT_CATEGORIES = [
    ("Transport", "🚕"),
    ("Accommodation", "🏨"),
    ("Food & drink", "🍜"),
    ("Hospital & medicine", "💊"),
    ("Translation", "💬"),
    ("Shopping", "🛍️"),
    ("Activities", "🎟️"),
    ("Other", "📦"),
]
# The default names are stored in English and translated when shown (Category.label), so one
# translation serves every trip.
DEFAULT_LABELS = {
    "Transport": pgettext_lazy("expense type", "Transport"),
    "Accommodation": pgettext_lazy("expense type", "Accommodation"),
    "Food & drink": pgettext_lazy("expense type", "Food & drink"),
    "Hospital & medicine": pgettext_lazy("expense type", "Hospital & medicine"),
    "Translation": pgettext_lazy("expense type", "Translation"),
    "Shopping": pgettext_lazy("expense type", "Shopping"),
    "Activities": pgettext_lazy("expense type", "Activities"),
    "Other": pgettext_lazy("expense type", "Other"),
}
DEFAULT_EMOJI = "🏷️"

# The icons a type can have, shown as a grid when a traveler picks one.
EMOJI_CHOICES = [
    "🏷️", "🍜", "🍔", "🍕", "🥗", "☕", "🍺", "🍷", "🥤", "🛒",
    "🚕", "🚌", "🚆", "✈️", "⛴️", "🚗", "🛵", "⛽", "🅿️", "🧳",
    "🏨", "🏠", "⛺", "🎟️", "🎭", "🏛️", "🏖️", "🧗", "💆", "🎁",
    "💊", "🏥", "💬", "📱", "💻", "🔌", "🛍️", "👕", "💐", "📚",
    "🧺", "🧴", "💈", "🐶", "👶", "💵", "🏧", "🧾", "📦", "🔧",
]  # fmt: skip


class Category(models.Model):
    """A type of expense (Food & drink, Transport, ...). Each trip has its own list."""

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="categories")
    name = models.CharField(_("name"), max_length=40)
    name_en = models.CharField(_("name in English"), max_length=40, blank=True)
    emoji = models.CharField(_("icon"), max_length=16, default=DEFAULT_EMOJI)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = _("type")
        constraints = [
            models.UniqueConstraint(
                models.functions.Lower("name"), "trip", name="category_name_unique_in_trip"
            )
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def label(self) -> str:
        """The name as the reader sees it: a default type in the reader's language; any other
        type as written (its English copy in English)."""
        if self.name in DEFAULT_LABELS:
            return str(DEFAULT_LABELS[self.name])
        return english.shown(self, "name")


def add_default_categories(trip: Trip) -> None:
    Category.objects.bulk_create(
        Category(trip=trip, name=name, emoji=emoji, position=i)
        for i, (name, emoji) in enumerate(DEFAULT_CATEGORIES)
    )


class ActiveExpenseManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Expense(models.Model):
    # People are RESTRICT, not PROTECT: a person used in an expense cannot be deleted alone,
    # but deleting the whole trip deletes its expenses and people together.
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="expenses")
    date = models.DateField(_("date"))
    payer = models.ForeignKey(
        Participant, on_delete=models.RESTRICT, related_name="payments", verbose_name=_("paid by")
    )
    beneficiaries = models.ManyToManyField(
        Participant,
        related_name="benefits",
        verbose_name=_("for whom"),
        help_text=_("The amount is split equally among these people."),
    )
    # Empty only for deleted expenses whose type was removed later; a type in use cannot be removed.
    category = models.ForeignKey(
        Category,
        null=True,
        on_delete=models.SET_NULL,
        related_name="expenses",
        verbose_name=_("type"),
    )
    description = models.CharField(_("description"), max_length=200, blank=True)
    description_en = models.CharField(_("description in English"), max_length=200, blank=True)
    amount = models.DecimalField(_("amount"), max_digits=14, decimal_places=2)
    currency = models.CharField(_("currency"), max_length=3, choices=CURRENCY_CHOICES)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    # The order within a day, set by dragging a card. New expenses get 0, so they come first
    # until the day is reordered (ties fall back to newest first).
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = ActiveExpenseManager()
    all_objects = models.Manager()  # noqa: DJ012 - ruff reads models.Manager() as a field

    class Meta:
        ordering = ["-date", "position", "-created_at"]
        base_manager_name = "all_objects"
        indexes = [
            models.Index(
                fields=["trip", "date"],
                name="expense_trip_date",
                condition=models.Q(deleted_at__isnull=True),
            ),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="amount_positive")
        ]

    def __str__(self) -> str:
        return self.description or (self.category.name if self.category else "")
