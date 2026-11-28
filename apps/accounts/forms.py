from django import forms
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.utils.translation import gettext_lazy as _

from .backends import AccountClosed

CLOSED = _("This account is closed. Ask the admin to restore it.")


class ClosedAccountMessage:
    """A closed account with the right password sees that it is closed (spec section 6.5).

    The backend raises ``AccountClosed`` only after django-axes has allowed the attempt and the
    password was right, so a locked login stays locked and the message never confirms a guessed
    password. It is not reported as a failed login, so axes does not count it.
    """

    def clean(self):
        try:
            return super().clean()
        except AccountClosed:
            raise forms.ValidationError(CLOSED, code="closed") from None


class LoginForm(ClosedAccountMessage, AuthenticationForm):
    """Sign-in accepts any letter case; the backend lowercases the name."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(autocapitalize="none", spellcheck="false")


class AdminLoginForm(ClosedAccountMessage, AdminAuthenticationForm):
    """Django's admin login, which would otherwise fail with an error page on a closed account."""


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
        self.fields["username"].help_text = self.confirm_text()

    def confirm_text(self) -> str:
        return _("Type “%(username)s” to confirm.") % {"username": self.user.username}

    def clean_username(self):
        typed = self.cleaned_data["username"].strip().lower()
        if typed != self.user.username:
            raise forms.ValidationError(self.confirm_text())
        return typed
