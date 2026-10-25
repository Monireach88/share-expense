from django import forms
from django.utils.translation import gettext_lazy as _

from apps.trips.forms import DATE_INPUT
from apps.trips.models import Trip

from .models import Expense


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["amount", "currency", "description", "category", "payer", "beneficiaries", "date"]
        widgets = {
            "beneficiaries": forms.CheckboxSelectMultiple,
            "date": DATE_INPUT,
            "amount": forms.NumberInput(
                attrs={"inputmode": "decimal", "step": "0.01", "min": "0.01"}
            ),
        }

    def __init__(self, *args, trip: Trip, **kwargs):
        super().__init__(*args, **kwargs)
        self.trip = trip
        participants = trip.participants.all()
        # Only this trip's people can be chosen, so IDs from another trip are rejected.
        self.fields["payer"].queryset = participants
        self.fields["payer"].empty_label = None
        self.fields["beneficiaries"].queryset = participants
        currencies = trip.currencies()
        self.fields["currency"].choices = [(c, c) for c in currencies]

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
