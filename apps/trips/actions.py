"""Changes to a trip's state and its accounts, one function per action.

Each function runs in one transaction and receives ``by``, the membership of the person who
acts, so a History entry can later be written in the same place and the same transaction.
The views check the role; these functions check the rules that hold whoever calls them.
"""

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.settlement.engine import SettlementError

from .access import lock_trip
from .models import Trip, TripMember
from .summary import trip_settlement


class ActionRefused(Exception):
    """The action breaks a trip rule; the message says why, in words for the person."""


def settle(trip: Trip, *, by: TripMember) -> None:
    with transaction.atomic():
        trip = lock_trip(trip)
        if trip.is_settled:
            return
        try:
            trip_settlement(trip)
        except SettlementError as error:
            raise ActionRefused(
                _("The trip cannot be settled: %(error)s.") % {"error": error}
            ) from error
        trip.settled_at = timezone.now()
        trip.save(update_fields=["settled_at", "updated_at"])


def reopen(trip: Trip, *, by: TripMember) -> None:
    with transaction.atomic():
        trip = lock_trip(trip)
        if not trip.is_settled:
            return
        trip.settled_at = None
        trip.save(update_fields=["settled_at", "updated_at"])


def change_role(member: TripMember, role: str, *, by: TripMember) -> None:
    """Make an account a Member or an Editor. The Owner's own role changes only by transfer."""
    if member.is_owner:
        raise ActionRefused(_("The Owner's role changes only by making someone else the Owner."))
    if role not in (TripMember.Role.MEMBER, TripMember.Role.EDITOR):
        raise ActionRefused(_("Choose Member or Editor."))
    if member.role == role:
        return
    with transaction.atomic():
        member.role = role
        member.save(update_fields=["role"])


def transfer_ownership(new_owner: TripMember, *, by: TripMember) -> None:
    """Make another approved account on the trip the Owner; the old Owner becomes an Editor."""
    if not by.is_owner:
        raise ActionRefused(_("Only the Owner can do this."))
    if new_owner.pk == by.pk or new_owner.trip_id != by.trip_id:
        raise ActionRefused(_("Choose another account on this trip."))
    if not new_owner.user.is_active:
        raise ActionRefused(_("This account is not approved yet."))
    with transaction.atomic():
        lock_trip(by.trip)
        # One owner per trip is a database rule, so the old owner steps down first.
        by.role = TripMember.Role.EDITOR
        by.save(update_fields=["role"])
        new_owner.role = TripMember.Role.OWNER
        new_owner.save(update_fields=["role"])


def remove_member(member: TripMember, *, by: TripMember) -> None:
    """Take an account off the trip: it loses access at once and its traveler is unlinked."""
    if member.is_owner:
        raise ActionRefused(_("The Owner cannot be removed."))
    with transaction.atomic():
        member.trip.participants.filter(user_id=member.user_id).update(user=None)
        member.delete()
