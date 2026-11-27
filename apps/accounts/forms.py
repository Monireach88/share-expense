from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.utils.translation import gettext_lazy as _

from .models import User

CLOSED = _("This account is closed. Ask the admin to restore it.")


class LoginForm(AuthenticationForm):
    """Sign-in accepts any letter case; the backend lowercases the name.

    A closed account with the right password sees that it is closed (spec section 6.5). This is
    checked before Django's ``authenticate``, so django-axes, which counts failures reported by
    ``authenticate``, never counts it as a wrong password. A wrong password still counts.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(autocapitalize="none", spellcheck="false")

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        if username and password:
            closed = User.objects.filter(
                username=username.strip().lower(), closed_at__isnull=False
            ).first()
            if closed is not None and closed.check_password(password):
                raise forms.ValidationError(CLOSED, code="closed")
        return super().clean()


class PlainPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].help_text = _("At least 8 characters, not only numbers.")
        self.fields["new_password2"].help_text = _("Type the new password again.")


class CloseAccountForm(forms.Form):
    """The person types their username to confirm that they close their account."""

    username = forms.CharField(label=_("Your username"), max_length=150)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["username"].widget.attrs.update(
            autocapitalize="none", spellcheck="false", autocomplete="off"
        )

    def clean_username(self):
        typed = self.cleaned_data["username"].strip().lower()
        if typed != self.user.username:
            raise forms.ValidationError(
                _("Type your username, %(username)s, to confirm.")
                % {"username": self.user.username}
            )
        return typed
