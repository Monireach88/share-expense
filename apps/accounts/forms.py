from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils.translation import gettext_lazy as _

from .models import User


class SignupRequestForm(UserCreationForm):
    first_name = forms.CharField(label=_("Your name"), max_length=150)

    class Meta:
        model = User
        fields = ("username", "first_name")

    def save(self, commit: bool = True) -> User:
        user = super().save(commit=False)
        user.is_active = False
        if commit:
            user.save()
        return user
