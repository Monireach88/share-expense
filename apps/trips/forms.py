from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from .models import ExchangeRate, Participant, Trip, TripMember

DATE_INPUT = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class TripForm(forms.ModelForm):
    class Meta:
        model = Trip
        fields = ["name", "country", "start_date", "end_date", "base_currency"]
        widgets = {"start_date": DATE_INPUT, "end_date": DATE_INPUT}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        country = self.fields["country"]
        country.choices = [("", _("Choose a country (optional)")), *list(country.choices)[1:]]
        if self.instance.pk and self.instance.is_settled:
            # The base currency changes every balance, so it is locked with the expenses.
            self.fields["base_currency"].disabled = True

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", _("The end date must be on or after the start date."))
        if (
            self.instance.pk
            and "base_currency" in self.changed_data
            and self.instance.rates.filter(currency=cleaned.get("base_currency")).exists()
        ):
            self.add_error("base_currency", _("Delete the exchange rate for this currency first."))
        return cleaned


class ExchangeRateForm(forms.ModelForm):
    class Meta:
        model = ExchangeRate
        fields = ["currency", "rate"]

    def __init__(self, *args, trip: Trip, **kwargs):
        super().__init__(*args, **kwargs)
        self.trip = trip
        currency = self.fields["currency"]
        currency.choices = [("", _("Choose")), *list(currency.choices)[1:]]

    def clean_currency(self):
        currency = self.cleaned_data["currency"]
        if currency == self.trip.base_currency:
            raise forms.ValidationError(_("This is already the trip's base currency."))
        return currency

    def clean_rate(self):
        rate = self.cleaned_data["rate"]
        if rate <= 0:
            raise forms.ValidationError(_("Enter a rate above zero."))
        return rate


class ParticipantForm(forms.ModelForm):
    class Meta:
        model = Participant
        fields = ["name", "user", "sponsors"]
        widgets = {"sponsors": forms.CheckboxSelectMultiple}

    def __init__(self, *args, trip: Trip, **kwargs):
        super().__init__(*args, **kwargs)
        self.trip = trip
        if trip.is_settled:
            # A settled trip keeps its travelers and covers; linking an account changes no number.
            self.fields["name"].disabled = True
            self.fields["sponsors"].disabled = True
        # Only travelers who pay for themselves can cover someone, so only they are offered.
        others = trip.participants.filter(sponsors__isnull=True)
        if self.instance.pk:
            others = others.exclude(pk=self.instance.pk)
        self.fields["sponsors"].queryset = others.distinct()
        self.fields["user"].queryset = get_user_model().objects.filter(memberships__trip=trip)
        self.fields["user"].label_from_instance = lambda u: f"{u.display_name} ({u.username})"
        self.fields["user"].empty_label = _("No account")
        self.fields["user"].help_text = _(
            "Optional. Link the person's own account so the app can show them their balance."
        )
        self.fields["sponsors"].label = _("Covered by")
        self.fields["sponsors"].help_text = _(
            "Travelers who pay this traveler's share. Empty means they pay their own."
        )

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        clash = self.trip.participants.filter(name__iexact=name)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(_("Someone on this trip already has this name."))
        return name

    def clean_user(self):
        user = self.cleaned_data["user"]
        if user is None:
            return user
        taken = self.trip.participants.filter(user=user)
        if self.instance.pk:
            taken = taken.exclude(pk=self.instance.pk)
        if other := taken.first():
            raise forms.ValidationError(
                _("This account is already linked to %(name)s.") % {"name": other.name}
            )
        return user

    def clean_sponsors(self):
        sponsors = self.cleaned_data["sponsors"]
        if not sponsors:
            return sponsors
        if self.instance.pk and self.instance.sponsored.exists():
            raise forms.ValidationError(
                _("This person already covers someone else, so they must pay for themselves.")
            )
        for sponsor in sponsors:
            if sponsor.sponsors.exists():
                raise forms.ValidationError(
                    _("%(name)s is covered by someone else and cannot cover another person.")
                    % {"name": sponsor.name}
                )
        return sponsors


class MemberAddForm(forms.Form):
    username = forms.CharField(label=_("Username"), max_length=150)

    def __init__(self, *args, trip: Trip, **kwargs):
        super().__init__(*args, **kwargs)
        self.trip = trip

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        user = get_user_model().objects.filter(username__iexact=username, is_active=True).first()
        if user is None:
            raise forms.ValidationError(_("No approved account has this username."))
        if TripMember.objects.filter(trip=self.trip, user=user).exists():
            raise forms.ValidationError(_("This account is already on the trip."))
        self.user = user
        return username


class MemberRoleForm(forms.Form):
    """The Owner makes an account a Member or an Editor."""

    role = forms.ChoiceField(
        label=_("Role"),
        choices=[
            (TripMember.Role.MEMBER, _("Member")),
            (TripMember.Role.EDITOR, _("Editor")),
        ],
        widget=forms.RadioSelect,
        help_text=_(
            "A Member changes only expenses their own traveler paid. "
            "An Editor changes every expense and can settle the trip."
        ),
    )
