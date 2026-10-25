"""Object-level access checks. Every trip view goes through ``get_membership``."""

from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest

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
