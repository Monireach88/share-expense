"""How Google sign-in (django-allauth) fits this app's accounts (spec sections 6.3 and 6.4).

- A Google sign-in is matched only by the Google account itself (its stable id, stored when
  Google is linked), never by an email address typed into an account (settings turn email
  matching off).
- New accounts are made only inside a personal invite: sign-up is open only while the session
  holds a live invite whose address equals Google's verified address. They are approved at once.
- Google sign-in with no linked account and no such invite is refused; nothing is created.
- A closed account cannot sign in with Google either.
- allauth itself refuses to remove the only Google connection of an account without a password.
"""

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.providers.base import AuthProcess
from django.contrib import messages
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.trips import invites
from apps.trips.invite_views import SESSION_KEY

from . import usernames
from .models import User

CLOSED = _("This account is closed. Ask the admin to restore it.")


def notice(request, text: str):
    return render(request, "trips/invite_notice.html", {"text": text}, status=403)


def _session_invite(request):
    """The live invite this browser opened before going to Google, or None."""
    invite = invites.find_by_token(request.session.get(SESSION_KEY, ""))
    return invite if invites.is_live(invite) else None


def verified_email(sociallogin) -> str:
    """The address Google says it has verified, in lowercase, or ""."""
    for address in sociallogin.email_addresses:
        if address.verified and address.email:
            return address.email.strip().lower()
    return ""


class AccountAdapter(DefaultAccountAdapter):
    def generate_unique_username(self, txts, regex=None):
        """A Google account gets a username built from its email name (spec section 6.1)."""
        return usernames.generate_username(
            txts, lambda name: User.objects.filter(username=name).exists()
        )

    def is_open_for_signup(self, request):
        return False  # allauth's own sign-up form is never used.

    def get_login_redirect_url(self, request):
        # A Google sign-in that began at an invite link goes back to it, which accepts it.
        if token := request.session.get(SESSION_KEY):
            return reverse("invite", args=[token])
        return super().get_login_redirect_url(request)

    def add_message(self, request, level, *args, **kwargs):
        # allauth's own notes ("Successfully signed in as ...") repeat what the page shows.
        if level >= messages.WARNING:
            super().add_message(request, level, *args, **kwargs)


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        if sociallogin.state.get("process") == AuthProcess.CONNECT:
            return  # Linking Google from the account menu: the person is signed in already.
        user = sociallogin.user if sociallogin.is_existing else None
        if user is not None and user.is_closed:
            raise ImmediateHttpResponse(notice(request, CLOSED))
        invite = _session_invite(request)
        if invite is not None:
            if verified_email(sociallogin) != invite.email:
                request.session.pop(SESSION_KEY, None)
                text = _(
                    "This invite is for %(address)s, but you used another Google account. Sign "
                    "out of Google, then open the invite link again and choose the invited address."
                ) % {"address": invites.mask(invite.email)}
                raise ImmediateHttpResponse(notice(request, text))
            return  # Signs in, or signs up below; the invite page then accepts the invite.
        if user is None:
            raise ImmediateHttpResponse(
                notice(
                    request,
                    _(
                        "No account uses this Google account. If you have a username and "
                        "password, log in with them and link Google from the account menu. To "
                        "join a trip, ask its Owner for an invite."
                    ),
                )
            )

    def is_open_for_signup(self, request, sociallogin):
        invite = _session_invite(request)
        return invite is not None and verified_email(sociallogin) == invite.email

    def save_user(self, request, sociallogin, form=None):
        sociallogin.user.is_active = True  # Made from a personal invite: approved at once.
        return super().save_user(request, sociallogin, form)
