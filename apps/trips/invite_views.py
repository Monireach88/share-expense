"""The page a personal invite link opens (spec section 6.3), and the old shared links.

It is reached by a secret token, not by a trip id, so it does not start with ``get_membership``.
Before acceptance it shows only the trip name, who invited, and the invited address partly hidden.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from . import invites
from .models import TripMember

SESSION_KEY = "invite_token"  # Kept for Google sign-in, which leaves the site and comes back.


def gone(request: HttpRequest) -> HttpResponse:
    request.session.pop(SESSION_KEY, None)
    return render(request, "trips/invite_gone.html", status=404)


@login_not_required
def invite_page(request: HttpRequest, token: str) -> HttpResponse:
    invite = invites.find_by_token(token)
    if invite is None:
        return gone(request)
    invites.expire_if_due(invite)
    user, trip = request.user, invite.trip
    if user.is_authenticated and TripMember.objects.filter(trip=trip, user=user).exists():
        request.session.pop(SESSION_KEY, None)
        return redirect("trip", trip_id=trip.id)
    if not invites.is_live(invite):
        return gone(request)
    if user.is_authenticated:
        if invites.google_email(user).lower() != invite.email:
            return render(
                request,
                "trips/invite_notice.html",
                {
                    "text": _(
                        "You are signed in as %(name)s. Sign out first, then open this link again."
                    )
                    % {"name": user.display_name},
                    "sign_out": True,
                },
            )
        request.session.pop(SESSION_KEY, None)
        try:
            invites.accept(invite, token, user)
        except invites.InviteRefused:
            return gone(request)
        messages.success(request, _("You joined %(trip)s.") % {"trip": trip.name})
        return redirect("trip", trip_id=trip.id)
    request.session[SESSION_KEY] = token
    return render(
        request,
        "trips/invite.html",
        {
            "trip_name": trip.name,
            "inviter": invite.invited_by_name,
            "address": invites.mask(invite.email),
            "next": request.path,
        },
    )


@login_not_required
def old_join_link(request: HttpRequest, token: str) -> HttpResponse:
    """The shared invite link was removed; every old address shows that it no longer works."""
    return render(request, "trips/invite_gone.html", status=404)
