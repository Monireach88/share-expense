"""Changes to a trip's state and its accounts, one function per action.

Each function runs in one transaction and receives ``by``, the membership of the person who
acts, so a History entry can later be written in the same place and the same transaction.
The views check the role; these functions check the rules that hold whoever calls them.
"""

import secrets

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.disputes import rules as disputes
from apps.disputes.models import Dispute, Notification
from apps.settlement.engine import SettlementError

from . import history
from .access import lock_trip
from .models import Participant, RemovedAccount, Trip, TripMember
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
        # The invite link stays closed to this account until the Owner adds it again.
        RemovedAccount.objects.get_or_create(trip=trip, user=member.user)
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


def add_member(
    trip: Trip,
    user,
    *,
    by: TripMember,
    traveler: Participant | None = None,
    new_traveler: bool = False,
) -> TripMember:
    """Give an approved account access to the trip, as a Member (spec section 6.2).

    The account is either linked to ``traveler`` (a traveler with no account), or gets a new
    traveler with its name (``new_traveler``), or stays a "Viewer" (neither). Adding an account
    the Owner removed earlier clears its block on the invite link.
    """
    with transaction.atomic():
        lock_trip(trip)
        if new_traveler:
            if trip.is_settled:
                raise ActionRefused(_("This trip is settled, so its travelers are locked."))
            if trip.participants.filter(name__iexact=user.display_name).exists():
                raise ActionRefused(_("Someone on this trip already has this name."))
            traveler = Participant.objects.create(trip=trip, name=user.display_name, user=user)
        elif traveler is not None:
            traveler = Participant.objects.select_for_update().get(pk=traveler.pk, trip=trip)
            if traveler.user_id is not None:
                raise ActionRefused(_("This traveler is already linked to an account."))
            before = history.traveler_state(traveler)
            traveler.user = user
            traveler.save(update_fields=["user"])
        member = TripMember.objects.create(trip=trip, user=user)
        RemovedAccount.objects.filter(trip=trip, user=user).delete()
        if new_traveler:
            # "Added traveler X" and "added X's account" already say the two are linked.
            history.record(
                trip, by, "added", "traveler", object_id=traveler.pk, label=traveler.name
            )
        history.record(trip, by, "added", "account", object_id=member.pk, label=user.display_name)
        if traveler is not None and not new_traveler:
            history.record_traveler_changes(trip, by, traveler, before)
    return member


# --- Invite link (spec section 6.3) ---------------------------------------------------------


def _new_token() -> str:
    return secrets.token_urlsafe(24)


def set_invite_link(trip: Trip, change: str, *, by: TripMember) -> None:
    """``change`` is "on", "off" or "renew". Turning on a link that is on does nothing."""
    with transaction.atomic():
        trip = lock_trip(trip)
        if change == "on" and trip.invite_token is None:
            trip.invite_token, action = _new_token(), "invite_on"
        elif change == "renew" and trip.invite_token is not None:
            trip.invite_token, action = _new_token(), "invite_renewed"
        elif change == "off" and trip.invite_token is not None:
            trip.invite_token, action = None, "invite_off"
        else:
            return
        trip.save(update_fields=["invite_token", "updated_at"])
        history.record(trip, by, action, "trip", object_id=trip.pk, label=trip.name)


class JoinRefused(Exception):
    """Joining by link failed; ``reason`` is "gone", "removed", "taken" or "invalid"."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def join_by_link(token: str, user, traveler_id: str) -> Trip:
    """Make ``user`` a Member of the trip behind ``token``, linked to a traveler or "none".

    Runs under a lock on the trip, so a link renewed a moment ago is refused ("gone") and two
    people picking the same traveler cannot both get it ("taken"). An account that is already on
    the trip changes nothing.
    """
    trip = Trip.objects.filter(invite_token=token).first() if token else None
    if trip is None:
        raise JoinRefused("gone")
    with transaction.atomic():
        trip = lock_trip(trip)
        if trip.invite_token != token:
            raise JoinRefused("gone")
        if TripMember.objects.filter(trip=trip, user=user).exists():
            return trip
        if RemovedAccount.objects.filter(trip=trip, user=user).exists():
            raise JoinRefused("removed")
        traveler = None
        if traveler_id != "none":
            try:
                traveler = Participant.objects.select_for_update().get(pk=traveler_id, trip=trip)
            except Participant.DoesNotExist, ValueError, ValidationError:
                raise JoinRefused("invalid") from None
            if traveler.user_id is not None:
                raise JoinRefused("taken")
            traveler.user = user
            try:
                with transaction.atomic():
                    traveler.save(update_fields=["user"])
            except IntegrityError:  # The account is already linked to another traveler here.
                raise JoinRefused("taken") from None
        member = TripMember.objects.create(trip=trip, user=user)
        history.record(
            trip,
            user,
            "joined",
            "account",
            object_id=member.pk,
            label=user.display_name,
            values={"via": "link", "traveler": traveler.name if traveler else ""},
        )
    return trip
