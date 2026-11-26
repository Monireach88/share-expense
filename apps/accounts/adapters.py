"""How Google sign-in (django-allauth) fits this app's accounts.

- An account whose email matches the verified Google email signs in (settings turn this on).
- A Google account that matches no account becomes a new account that waits for the admin's
  approval, exactly like a request from the sign-up page.
- allauth itself refuses to remove the only Google connection of an account without a password.
"""

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib import messages


class AccountAdapter(DefaultAccountAdapter):
    def add_message(self, request, level, *args, **kwargs):
        # allauth's own notes ("Successfully signed in as ...") repeat what the page shows.
        if level >= messages.WARNING:
            super().add_message(request, level, *args, **kwargs)


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def save_user(self, request, sociallogin, form=None):
        sociallogin.user.is_active = False  # The admin approves new accounts.
        return super().save_user(request, sociallogin, form)
