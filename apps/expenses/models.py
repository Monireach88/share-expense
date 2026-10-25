import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.trips.currencies import CURRENCY_CHOICES
from apps.trips.models import Participant, Trip


class Category(models.TextChoices):
    TRANSPORT = "transport", _("Transport")
    ACCOMMODATION = "accommodation", _("Accommodation")
    FOOD = "food", _("Food & drink")
    MEDICAL = "medical", _("Hospital & medicine")
    TRANSLATION = "translation", _("Translation")
    SHOPPING = "shopping", _("Shopping")
    ACTIVITIES = "activities", _("Activities")
    OTHER = "other", _("Other")


class ActiveExpenseManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Expense(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="expenses")
    date = models.DateField(_("date"))
    payer = models.ForeignKey(
        Participant, on_delete=models.PROTECT, related_name="payments", verbose_name=_("paid by")
    )
    beneficiaries = models.ManyToManyField(
        Participant,
        related_name="benefits",
        verbose_name=_("for whom"),
        help_text=_("The amount is split equally among these people."),
    )
    category = models.CharField(
        _("type"), max_length=20, choices=Category.choices, default=Category.FOOD
    )
    description = models.CharField(_("description"), max_length=200, blank=True)
    amount = models.DecimalField(_("amount"), max_digits=14, decimal_places=2)
    currency = models.CharField(_("currency"), max_length=3, choices=CURRENCY_CHOICES)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = ActiveExpenseManager()
    all_objects = models.Manager()  # noqa: DJ012 - ruff reads models.Manager() as a field

    class Meta:
        ordering = ["-date", "-created_at"]
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
        return self.description or self.get_category_display()
