"""The page an invite link opens (spec section 6.3).

It is reached by a secret token, not by a trip id, so it does not start with ``get_membership``.
What it shows depends on who asks: a visitor without an account sees only the trip name; a
signed-in approved account sees the names of the travelers who have no account yet.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_not_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _

from . import actions
from .models import RemovedAccount, Trip, TripMember

TOKEN_SESSION_KEY = "invite_token"
NONE = "none"


def _dead(request: HttpRequest) -> HttpResponse:
    return render(request, "trips/join_dead.html", status=404)


@login_not_required
def join(request: HttpRequest, token: str) -> HttpResponse:
    user = request.user
    if user.is_authenticated and user.invite_token:
        # A sign-in that came from a link brought the account here; the memory is used up.
        get_user_model().objects.filter(pk=user.pk).update(invite_token="")
        request.session.pop(TOKEN_SESSION_KEY, None)
    trip = Trip.objects.filter(invite_token=token).first()
    if trip is None:
        return _dead(request)
    if not user.is_authenticated:
        # Kept for a Google sign-in, which leaves the site and comes back.
        request.session[TOKEN_SESSION_KEY] = token
        return render(
            request,
            "trips/join_visitor.html",
            {"trip": trip, "token": token, "next": reverse("join", args=[token])},
        )
    if TripMember.objects.filter(trip=trip, user=user).exists():
        return redirect("trip", trip_id=trip.id)
    if RemovedAccount.objects.filter(trip=trip, user=user).exists():
        return render(request, "trips/join_removed.html", {"trip": trip})
    error = ""
    if request.method == "POST":
        choice = request.POST.get("traveler", "")
        try:
            actions.join_by_link(token, user, choice)
        except actions.JoinRefused as refused:
            if refused.reason == "gone":
                return _dead(request)
            if refused.reason == "removed":
                return render(request, "trips/join_removed.html", {"trip": trip})
            error = (
                _("Already taken, choose again.")
                if refused.reason == "taken"
                else _("Choose who you are.")
            )
        else:
            return redirect("trip", trip_id=trip.id)
    return render(
        request,
        "trips/join.html",
        {
            "trip": trip,
            "travelers": trip.participants.filter(user__isnull=True),
            "error": error,
            "none": NONE,
        },
    )
