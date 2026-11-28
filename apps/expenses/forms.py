from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.trips.english import ENGLISH_LABEL, EnglishCopyMixin
from apps.trips.forms import DATE_INPUT
from apps.trips.models import Trip

from .models import EMOJI_CHOICES, Category, Expense

OTHER_DATE = "other"


class AmountField(forms.DecimalField):
    """Accepts "450,000" and "450 000" as well as "450000", because people type amounts that way."""

    def to_python(self, value):
        if isinstance(value, str):
            value = value.replace(",", "").replace(" ", "").replace(" ", "")
        return super().to_python(value)


class ExpenseForm(EnglishCopyMixin, forms.ModelForm):
    english_fields = {"description": "description_en"}

    class Meta:
        model = Expense
        fields = [
            "amount",
            "currency",
            "description",
            "description_en",
            "payer",
            "beneficiaries",
            "category",
            "date",
        ]
        field_classes = {"amount": AmountField}
        labels = {
            "description": _("Description"),
            "description_en": ENGLISH_LABEL,
            "payer": _("Paid by"),
            "beneficiaries": _("Split between"),
            "category": _("Type"),
            "date": _("Date"),
        }
        widgets = {
            "amount": forms.TextInput(
                attrs={"inputmode": "decimal", "autocomplete": "off", "placeholder": "0"}
            ),
            "currency": forms.RadioSelect,
            # One line that grows downward as the text wraps; Enter saves the form (expense_form.js).
            "description": forms.Textarea(
                attrs={
                    "rows": 1,
                    "placeholder": _("e.g. Taxi from the airport"),
                    "autocomplete": "off",
                    "enterkeyhint": "done",
                }
            ),
            "description_en": forms.Textarea(attrs={"rows": 1, "autocomplete": "off"}),
            "payer": forms.RadioSelect,
            "beneficiaries": forms.CheckboxSelectMultiple,
            "category": forms.RadioSelect,
            "date": DATE_INPUT,
        }
        help_texts = {"beneficiaries": ""}

    def __init__(self, data=None, *args, trip: Trip, payer_only=None, **kwargs):
        """``payer_only``: the one traveler a Member may record as payer (their own); the form
        then offers only that traveler. The view refuses another payer with 403 before this."""
        # Day chips post date=other when the user picks "Other date"; the real value is in date_other.
        if data is not None and data.get("date") == OTHER_DATE:
            data = data.copy()
            data["date"] = data.get("date_other", "")
        super().__init__(data, *args, **kwargs)
        self.trip = trip
        participants = trip.participants.all()
        # Only this trip's people can be chosen, so IDs from another trip are rejected.
        self.fields["payer"].queryset = (
            participants.filter(pk=payer_only.pk) if payer_only else participants
        )
        self.fields["payer"].empty_label = None
        if payer_only:
            self.fields["payer"].help_text = _(
                "Your account can add and change only expenses paid by %(name)s."
            ) % {"name": payer_only.name}
        self.fields["beneficiaries"].queryset = participants
        self.fields["currency"].choices = [(c, c) for c in trip.currencies()]
        self.fields["category"].queryset = trip.categories.all()
        self.fields["category"].empty_label = None
        self.fields["category"].required = True
        amount = self.initial.get("amount")
        if isinstance(amount, Decimal) and amount == amount.to_integral_value():
            self.initial["amount"] = amount.quantize(Decimal(1))

    def date_iso(self) -> str:
        """The chosen day as YYYY-MM-DD, to mark the matching day chip."""
        value = self["date"].value()
        return value.isoformat() if hasattr(value, "isoformat") else (value or "")

    def clean_description(self):
        # A description is one line: line breaks from the text box become single spaces.
        return " ".join(self.cleaned_data["description"].split())

    def clean_description_en(self):
        return " ".join(self.cleaned_data["description_en"].split())

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


class CategoryForm(EnglishCopyMixin, forms.ModelForm):
    """Add or rename a trip's expense type from the expense form."""

    english_fields = {"name": "name_en"}

    class Meta:
        model = Category
        fields = ["name", "name_en", "emoji"]

    def __init__(self, *args, trip: Trip, **kwargs):
        super().__init__(*args, **kwargs)
        self.trip = trip

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if not name:
            raise forms.ValidationError(_("Enter a name."))
        taken = self.trip.categories.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if taken.exists():
            raise forms.ValidationError(_("This trip already has a type with this name."))
        return name

    def clean_name_en(self):
        return " ".join(self.cleaned_data["name_en"].split())

    def clean_emoji(self):
        emoji = self.cleaned_data["emoji"]
        if emoji not in EMOJI_CHOICES:
            raise forms.ValidationError(_("Choose an icon from the list."))
        return emoji
