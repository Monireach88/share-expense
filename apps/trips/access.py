"""Object-level access checks. Every trip view goes through ``get_membership``."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.translation import gettext as _

from .models import TripMember


def get_membership(request: HttpRequest, trip_id, *, owner_only: bool = False) -> TripMember:
    """Return the user's membership of the trip.

    A user who is not a member gets 404, so trip IDs of other groups are not revealed.
    A member who is not the owner gets 403 on owner-only pages.
    """
    membership = (
        TripMember.objects.select_related("trip").filter(trip_id=trip_id, user=request.user).first()
    )
    if membership is None:
        raise Http404
    if owner_only and not membership.is_owner:
        raise PermissionDenied
    return membership


def locked(request: HttpRequest, trip) -> HttpResponse | None:
    """A settled trip is locked: a redirect for pages that would change its numbers, else None.

    Expenses, people (and who covers whom) and exchange rates all change the balances.
    """
    if not trip.is_settled:
        return None
    messages.error(request, _("This trip is settled, so its expenses are locked."))
    return redirect("trip", trip_id=trip.id)
