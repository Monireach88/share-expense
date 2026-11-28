from allauth.socialaccount.models import SocialAccount
from django import forms
from django.contrib.auth import get_user_model
from django.core.validators import validate_email
from django.utils.translation import gettext_lazy as _

from . import email_check
from .invites import VERIFIED_GOOGLE_EMAIL, google_user
from .models import ExchangeRate, Invite, Participant, Trip, TripMember

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
            "Optional. The linked account sees this traveler's balance and can add the "
            "expenses this traveler paid."
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


class InviteForm(forms.Form):
    """The Owner invites a person (spec section 6.2): an approved account, by username or by the
    address it signs in with through Google, joins at once; any other email address gets a
    personal invite. Each with one traveler choice: a free traveler, a new traveler, or none."""

    NEW = "new"
    NONE = "none"
    NOT_AN_ACCOUNT = _(
        "No account has this username. To invite someone new, type their email address."
    )

    who = forms.CharField(
        label=_("Username or email"),
        max_length=254,
        help_text=_("A username of an approved account, or the email address of a new person."),
    )
    traveler = forms.ChoiceField(
        label=_("Traveler"), widget=forms.RadioSelect, choices=[], required=True
    )
    new_name = forms.CharField(
        label=_("New traveler's name"),
        max_length=80,
        required=False,
    )

    def __init__(self, *args, trip: Trip, **kwargs):
        super().__init__(*args, **kwargs)
        self.trip = trip
        self.user = None  # An approved account that joins at once.
        self.email = ""  # Or the address of a personal invite.
        self.suggestion = ""  # "dan@gmail.com" when the typed domain looks like a typo of it.
        self.pending = None  # An open invite to the same address: offer Send again.
        self.participant = None
        invited = trip.invites.filter(state__in=Invite.OPEN_STATES, traveler__isnull=False).values(
            "traveler_id"
        )
        free = list(trip.participants.filter(user__isnull=True).exclude(pk__in=invited))
        choices = [(str(p.pk), p.name) for p in free]
        if not trip.is_settled:  # Travelers are locked on a settled trip.
            choices.append((self.NEW, _("A new traveler")))
        choices.append((self.NONE, _("No traveler (view only)")))
        self.fields["traveler"].choices = choices
        self._free = {str(p.pk): p for p in free}
        self.fields["who"].widget.attrs.update(
            autocapitalize="none", spellcheck="false", autocomplete="off"
        )

    def _on_trip(self, user) -> bool:
        return TripMember.objects.filter(trip=self.trip, user=user).exists()

    def clean_who(self):
        text = self.cleaned_data["who"].strip()
        if "@" not in text:
            user = get_user_model().objects.filter(username=text.lower()).first()
            if user is not None and self._on_trip(user):
                raise forms.ValidationError(_("This person is already on the trip."))
            if user is None or not user.is_active or user.is_closed:
                raise forms.ValidationError(self.NOT_AN_ACCOUNT)
            self.user = user
            return text
        try:
            validate_email(text)
        except forms.ValidationError:
            raise forms.ValidationError(self.NOT_AN_ACCOUNT) from None
        email = text.lower()
        linked = SocialAccount.objects.filter(
            VERIFIED_GOOGLE_EMAIL, provider="google", extra_data__email__iexact=email
        )
        if any(self._on_trip(account.user) for account in linked.select_related("user")):
            raise forms.ValidationError(_("This person is already on the trip."))
        self.user = google_user(email)
        if self.user is None:
            self.email = email
            self.pending = self.trip.invites.filter(
                state__in=Invite.OPEN_STATES, email__iexact=email
            ).first()
            if self.pending is not None:
                raise forms.ValidationError(_("This address already has an invite to this trip."))
            domain = email.rpartition("@")[2]
            if not email_check.receives_email(domain):
                raise forms.ValidationError(
                    _("No email can be delivered to %(domain)s. Check the address.")
                    % {"domain": domain}
                )
            self.suggestion = email_check.suggestion(email)
        return email

    def clean_traveler(self):
        choice = self.cleaned_data["traveler"]
        self.participant = self._free.get(choice)
        return choice

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("traveler") != self.NEW:
            cleaned["new_name"] = ""
            return cleaned
        name = (cleaned.get("new_name") or "").strip()
        cleaned["new_name"] = name
        if not name:
            self.add_error("new_name", _("Type the new traveler's name."))
        elif self.trip.participants.filter(name__iexact=name).exists() or (
            self.trip.invites.filter(
                state__in=Invite.OPEN_STATES, new_traveler_name__iexact=name
            ).exists()
        ):
            self.add_error("new_name", _("Someone on this trip already has this name."))
        return cleaned

    @property
    def new_traveler_name(self) -> str:
        return self.cleaned_data.get("new_name", "")

    @property
    def traveler_text(self) -> str:
        """The choice in words, for the confirmation: "as Dan" or "view only"."""
        if self.participant is not None:
            return self.participant.name
        return self.new_traveler_name


class MemberRoleForm(forms.Form):
    """The Owner makes an account a Member or an Editor."""

    role = forms.ChoiceField(
        label=_("Role"),
        choices=[
            (TripMember.Role.MEMBER, _("Member")),
            (TripMember.Role.EDITOR, _("Editor")),
        ],
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, traveler=None, **kwargs):
        super().__init__(*args, **kwargs)
        if traveler is not None:
            self.fields["role"].help_text = _(
                "A Member can change only the expenses that %(name)s paid. An Editor can "
                "change every expense and mark the trip as settled."
            ) % {"name": traveler.name}
