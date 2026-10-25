from django import forms
from django.contrib.auth.forms import PasswordChangeForm, UserCreationForm
from django.utils.translation import gettext_lazy as _

from .models import User


class SignupRequestForm(UserCreationForm):
    first_name = forms.CharField(label=_("Your name"), max_length=150)

    class Meta:
        model = User
        fields = ("username", "first_name")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].help_text = _("Letters and numbers, no spaces.")
        self.fields["password1"].help_text = _("At least 8 characters, not only numbers.")
        self.fields["password2"].help_text = _("Type the password again.")

    def save(self, commit: bool = True) -> User:
        user = super().save(commit=False)
        user.is_active = False
        if commit:
            user.save()
        return user


class PlainPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].help_text = _("At least 8 characters, not only numbers.")
        self.fields["new_password2"].help_text = _("Type the new password again.")
