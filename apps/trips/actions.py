"""Changes to a trip's state and its accounts, one function per action.

Each function runs in one transaction and receives ``by``, the membership of the person who
acts, so a History entry can later be written in the same place and the same transaction.
The views check the role; these functions check the rules that hold whoever calls them.
"""

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.disputes import rules as disputes
from apps.disputes.models import Dispute, Notification
from apps.settlement.engine import SettlementError

from . import history
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
        open_disputes = Dispute.objects.filter(trip=trip, state=Dispute.State.OPEN).count()
        if open_disputes:
            raise ActionRefused(
                _("The trip cannot be settled: %(reason)s.")
                % {"reason": disputes.open_count_text(open_disputes)}
            )
        try:
            trip_settlement(trip)
        except SettlementError as error:
            raise ActionRefused(
                _("The trip cannot be settled: %(error)s.") % {"error": error}
            ) from error
        trip.settled_at = timezone.now()
        trip.save(update_fields=["settled_at", "updated_at"])
        entry = history.record(trip, by, "settled", "trip", object_id=trip.pk, label=trip.name)
        disputes.notify_everyone(trip, Notification.Kind.SETTLED, by=by, entry=entry)


def reopen(trip: Trip, *, by: TripMember) -> None:
    with transaction.atomic():
        trip = lock_trip(trip)
        if not trip.is_settled:
            return
        trip.settled_at = None
        trip.save(update_fields=["settled_at", "updated_at"])
        entry = history.record(trip, by, "reopened", "trip", object_id=trip.pk, label=trip.name)
        disputes.notify_everyone(trip, Notification.Kind.REOPENED, by=by, entry=entry)


def change_role(member: TripMember, role: str, *, by: TripMember) -> None:
    """Make an account a Member or an Editor. The Owner's own role changes only by transfer."""
    if member.is_owner:
        raise ActionRefused(_("The Owner's role changes only by making someone else the Owner."))
    if role not in (TripMember.Role.MEMBER, TripMember.Role.EDITOR):
        raise ActionRefused(_("Choose Member or Editor."))
    if member.role == role:
        return
    with transaction.atomic():
        old = member.get_role_display()
        member.role = role
        member.save(update_fields=["role"])
        history.record(
            member.trip,
            by,
            "role_changed",
            "account",
            object_id=member.pk,
            label=member.user.display_name,
            changes={"role": history.change(old, member.get_role_display())},
        )


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
        history.record(
            by.trip,
            by,
            "became_owner",
            "account",
            object_id=new_owner.pk,
            label=new_owner.user.display_name,
        )


def remove_member(member: TripMember, *, by: TripMember) -> None:
    """Take an account off the trip: it loses access at once and its traveler is unlinked."""
    if member.is_owner:
        raise ActionRefused(_("The Owner cannot be removed."))
    with transaction.atomic():
        trip = member.trip
        name = member.user.display_name
        traveler = member.linked_traveler
        if traveler is not None:
            trip.participants.filter(pk=traveler.pk).update(user=None)
        history.record(trip, by, "removed", "account", object_id=member.pk, label=name)
        if traveler is not None:
            history.record(
                trip,
                by,
                "unlinked",
                "traveler",
                object_id=traveler.pk,
                label=traveler.name,
                changes={"account": history.change(name, "")},
            )
        member.delete()


def add_member(trip: Trip, user, *, by: TripMember) -> TripMember:
    """Give an approved account access to the trip, as a Member."""
    with transaction.atomic():
        member = TripMember.objects.create(trip=trip, user=user)
        history.record(trip, by, "added", "account", object_id=member.pk, label=user.display_name)
    return member
