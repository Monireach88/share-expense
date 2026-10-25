from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.trips.forms import DATE_INPUT
from apps.trips.models import Trip

from .models import Expense

OTHER_DATE = "other"


class AmountField(forms.DecimalField):
    """Accepts "450,000" and "450 000" as well as "450000", because people type amounts that way."""

    def to_python(self, value):
        if isinstance(value, str):
            value = value.replace(",", "").replace(" ", "").replace(" ", "")
        return super().to_python(value)


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["amount", "currency", "description", "payer", "beneficiaries", "category", "date"]
        field_classes = {"amount": AmountField}
        labels = {
            "description": _("What for?"),
            "payer": _("Who paid?"),
            "beneficiaries": _("For whom?"),
            "category": _("Type"),
            "date": _("Day"),
        }
        widgets = {
            "amount": forms.TextInput(
                attrs={"inputmode": "decimal", "autocomplete": "off", "placeholder": "0"}
            ),
            "currency": forms.RadioSelect,
            "description": forms.TextInput(
                attrs={"placeholder": _("e.g. Taxi from the airport"), "autocomplete": "off"}
            ),
            "payer": forms.RadioSelect,
            "beneficiaries": forms.CheckboxSelectMultiple,
            "category": forms.RadioSelect,
            "date": DATE_INPUT,
        }
        help_texts = {"beneficiaries": ""}

    def __init__(self, data=None, *args, trip: Trip, **kwargs):
        # Day chips post date=other when the user picks "Other date"; the real value is in date_other.
        if data is not None and data.get("date") == OTHER_DATE:
            data = data.copy()
            data["date"] = data.get("date_other", "")
        super().__init__(data, *args, **kwargs)
        self.trip = trip
        participants = trip.participants.all()
        # Only this trip's people can be chosen, so IDs from another trip are rejected.
        self.fields["payer"].queryset = participants
        self.fields["payer"].empty_label = None
        self.fields["beneficiaries"].queryset = participants
        self.fields["currency"].choices = [(c, c) for c in trip.currencies()]
        self.fields["category"].choices = [c for c in self.fields["category"].choices if c[0]]
        amount = self.initial.get("amount")
        if isinstance(amount, Decimal) and amount == amount.to_integral_value():
            self.initial["amount"] = amount.quantize(Decimal(1))

    def date_iso(self) -> str:
        """The chosen day as YYYY-MM-DD, to mark the matching day chip."""
        value = self["date"].value()
        return value.isoformat() if hasattr(value, "isoformat") else (value or "")

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError(_("Enter an amount above zero."))
        return amount

    def clean_currency(self):
        currency = self.cleaned_data["currency"]
        if currency not in self.trip.currencies():
            raise forms.ValidationError(
                _("Add an exchange rate for this currency in the trip settings first.")
            )
        return currency
