"""Closing an account (spec section 6.5).

The account becomes inactive and ``closed_at`` is set; every session of it ends. Its memberships
and traveler links stay unchanged, so the admin can restore it fully, and its name stays in the
records of its trips.
"""

from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.trips import history, invites
from apps.trips.access import lock_trip
from apps.trips.models import TripMember

from .models import User


class CloseRefused(Exception):
    """The account cannot be closed yet; the message says why."""


def owner_block(user: User) -> str:
    """Why the account cannot be closed yet, or "": it owns trips that have other accounts."""
    owned = TripMember.objects.filter(user=user, role=TripMember.Role.OWNER).select_related("trip")
    names = [m.trip.name for m in owned if m.trip.memberships.exclude(user=user).exists()]
    if not names:
        return ""
    trips = (
        names[0]
        if len(names) == 1
        else _("%(trips)s and %(last)s")
        % {
            "trips": ", ".join(names[:-1]),
            "last": names[-1],
        }
    )
    return _("You are the Owner of %(trips)s. Make someone else the Owner first.") % {
        "trips": trips
    }


def close_account(user: User) -> None:
    if blocked := owner_block(user):
        raise CloseRefused(blocked)
    with transaction.atomic():
        invites.cancel_owned_by(user)
        User.objects.filter(pk=user.pk).update(is_active=False, closed_at=timezone.now())
        for membership in user.memberships.select_related("trip"):
            lock_trip(membership.trip)
            history.record(
                membership.trip,
                user,
                "account_closed",
                "account",
                object_id=membership.pk,
                label=user.display_name,
            )
    end_sessions(user)


def end_sessions(user: User) -> None:
    """Delete every stored session signed in as ``user`` (sessions live in the database)."""
    user_id = str(user.pk)
    stale = [
        session.session_key
        for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator()
        if session.get_decoded().get("_auth_user_id") == user_id
    ]
    Session.objects.filter(session_key__in=stale).delete()
