"""How Google sign-in (django-allauth) fits this app's accounts.

- An account whose email matches the verified Google email signs in (settings turn this on).
- A Google account that matches no account becomes a new account that waits for the admin's
  approval, exactly like a request from the sign-up page.
- A new Google account keeps the invite link its visitor came from (kept in the session).
- allauth itself refuses to remove the only Google connection of an account without a password.
"""

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib import messages
from django.urls import reverse

from . import usernames
from .models import User


class AccountAdapter(DefaultAccountAdapter):
    def generate_unique_username(self, txts, regex=None):
        """A Google account gets a username built from its email name (spec section 6.1)."""
        return usernames.generate_username(
            txts, lambda name: User.objects.filter(username=name).exists()
        )

    def get_login_redirect_url(self, request):
        # A Google sign-in that began at an invite link goes on to that link's join page.
        if request.user.is_authenticated and request.user.invite_token:
            return reverse("join", args=[request.user.invite_token])
        return super().get_login_redirect_url(request)

    def add_message(self, request, level, *args, **kwargs):
        # allauth's own notes ("Successfully signed in as ...") repeat what the page shows.
        if level >= messages.WARNING:
            super().add_message(request, level, *args, **kwargs)


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def save_user(self, request, sociallogin, form=None):
        sociallogin.user.is_active = False  # The admin approves new accounts.
        # Keep the invite link this visitor came from; the first sign-in after approval opens it.
        sociallogin.user.invite_token = request.session.pop("invite_token", "")
        return super().save_user(request, sociallogin, form)
