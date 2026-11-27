"""Object-level access checks. Every trip view goes through ``get_membership``.

What each role may do lives on ``TripMember`` (``can_manage_expenses``, ``can_edit_expense`` ...);
this module turns those answers into 404, 403 or a "settled" redirect.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _

from .models import Trip, TripMember

SETTLED_MESSAGE = _("This trip is settled, so its expenses are locked.")


def get_membership(
    request: HttpRequest,
    trip_id,
    *,
    owner_only: bool = False,
    managers_only: bool = False,
    can_add: bool = False,
) -> TripMember:
    """Return the user's membership of the trip.

    A user who is not a member gets 404, so trip IDs of other groups are not revealed.
    A member without the needed role gets 403:
    ``owner_only`` for the Owner's pages, ``managers_only`` for Owner and Editors,
    ``can_add`` for anyone who may add an expense (everyone but a Viewer).
    """
    membership = (
        TripMember.objects.select_related("trip").filter(trip_id=trip_id, user=request.user).first()
    )
    if membership is None:
        raise Http404
    if owner_only and not membership.is_owner:
        raise PermissionDenied
    if managers_only and not membership.can_manage_expenses:
        raise PermissionDenied
    if can_add and not membership.can_add_expense:
        raise PermissionDenied
    return membership


def locked(request: HttpRequest, trip) -> HttpResponse | None:
    """A settled trip is locked: a redirect for pages that would change its numbers, else None.

    Expenses, types, people (and who covers whom) and exchange rates all change the balances.
    """
    if not trip.is_settled:
        return None
    messages.error(request, SETTLED_MESSAGE)
    return redirect("trip", trip_id=trip.id)


def lock_trip(trip) -> Trip:
    """Lock the trip row until the current transaction ends and return it fresh.

    Settling and every change to expenses take this lock, so an edit sent at the same moment
    as Settle waits for it and then sees the trip as settled. Call inside ``transaction.atomic``.
    """
    return Trip.objects.select_for_update().get(pk=trip.pk)
