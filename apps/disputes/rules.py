"""Who may open, write in, resolve and close a dispute, who is notified, and the actions themselves
(spec sections 4 and 5).

The views check the role (403); the action functions here check the state and the trip rules, run
in one transaction under the trip lock, and write the History entry and the notifications with it.
"""

from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.expenses.models import Expense
from apps.trips import history
from apps.trips.access import SETTLED_MESSAGE, lock_trip
from apps.trips.models import Trip, TripMember

from .models import Dispute, DisputeMessage, Notification


class DisputeRefused(Exception):
    """The action breaks a dispute rule; the message says why, in words for the person."""


# --- Who may do what ------------------------------------------------------------------------------


def involved_traveler_ids(trip: Trip, expense: Expense) -> set[str]:
    """The travelers who are, or were in any version History shows, the payer or in "For"."""
    ids = {
        str(expense.payer_id),
        *(str(pk) for pk in expense.beneficiaries.values_list("pk", flat=True)),
    }
    rows = trip.history.filter(object_type="expense", object_id=str(expense.pk))
    for values, changes in rows.values_list("values", "changes"):
        ids.add(values.get("payer_id"))
        ids.update(values.get("for_ids") or [])
        payer = changes.get("payer") or {}
        ids.update([payer.get("old_id"), payer.get("new_id")])
        people = changes.get("for") or {}
        ids.update([*(people.get("old_ids") or []), *(people.get("new_ids") or [])])
    ids.discard(None)
    return ids


def may_open(membership: TripMember, expense: Expense) -> bool:
    """§5.1: the account's linked traveler is or was the payer or in "For". A Viewer has no
    traveler, so never. The settled trip and the one-open-dispute rule are checked separately."""
    traveler = membership.linked_traveler
    return traveler is not None and str(traveler.pk) in involved_traveler_ids(
        membership.trip, expense
    )


def has_open_dispute(membership: TripMember, expense: Expense) -> bool:
    return expense.disputes.filter(opened_by=membership.user, state=Dispute.State.OPEN).exists()


def may_write(membership: TripMember, dispute: Dispute) -> bool:
    """§5.2: the opener (even after becoming a Viewer), the creator, the payer's account, the
    Owner and Editors (Editors may fix any expense, so they may write "Fixed")."""
    expense = dispute.expense
    user_id = membership.user_id
    return membership.can_manage_expenses or user_id in (
        dispute.opened_by_id,
        expense.created_by_id,
        expense.payer.user_id,
    )


def may_resolve(membership: TripMember, dispute: Dispute) -> bool:
    return dispute.opened_by_id is not None and membership.user_id == dispute.opened_by_id


def may_close(membership: TripMember) -> bool:
    return membership.is_owner


# --- Who is notified ------------------------------------------------------------------------------


def _trip_user_ids(trip: Trip) -> set:
    return set(trip.memberships.values_list("user_id", flat=True))


def _manager_ids(trip: Trip) -> set:
    """The Owner and the Editors, as they are now."""
    return set(
        trip.memberships.filter(
            role__in=[TripMember.Role.OWNER, TripMember.Role.EDITOR]
        ).values_list("user_id", flat=True)
    )


def _owner_id(trip: Trip):
    return (
        trip.memberships.filter(role=TripMember.Role.OWNER)
        .values_list("user_id", flat=True)
        .first()
    )


def dispute_people(dispute: Dispute) -> set:
    """Everyone in the dispute (§5.2): the opener, the creator, the payer's account, and the
    Owner or an Editor once they have written in it. Accounts no longer on the trip are skipped. When
    nobody but the opener is left, the Owner joins, so every dispute reaches someone."""
    trip, expense = dispute.trip, dispute.expense
    owner_id = _owner_id(trip)
    people = {dispute.opened_by_id, expense.created_by_id, expense.payer.user_id}
    people.update(
        dispute.messages.filter(author_id__in=_manager_ids(trip)).values_list(
            "author_id", flat=True
        )
    )
    people = {u for u in people if u in _trip_user_ids(trip)}
    if not people - {dispute.opened_by_id}:
        people.add(owner_id)
    people.discard(None)
    return people


def notify(
    trip: Trip,
    user_ids,
    kind: str,
    *,
    by,
    label: str = "",
    detail: str = "",
    opener: str = "",
    link: str,
):
    """One notification per account, never to the one who acted, nor to accounts off the trip."""
    actor = getattr(by, "user", by)
    on_trip = _trip_user_ids(trip)
    targets = {u for u in user_ids if u in on_trip and u != actor.pk}
    Notification.objects.bulk_create(
        Notification(
            user_id=user_id,
            trip=trip,
            kind=kind,
            actor_name=actor.display_name,
            label=label[:200],
            detail=detail[:200],
            opener_name=opener[:150],
            link=link,
        )
        for user_id in sorted(targets)
    )


def notify_everyone(trip: Trip, kind: str, *, by, entry, label: str = "", detail: str = ""):
    """Settling, reopening, and the Owner closing a dispute about her own expense (§2.1, §5.3)."""
    link = reverse("history", args=[trip.pk]) + f"#entry-{entry.pk}"
    notify(trip, _trip_user_ids(trip), kind, by=by, label=label, detail=detail, link=link)


def expense_link(trip: Trip, expense_id) -> str:
    return reverse("expense_edit", args=[trip.pk, expense_id]) + "#disputes"


def notification_text(item: Notification) -> str:
    data = {
        "who": item.actor_name,
        "label": f"“{item.label}”",
        "detail": item.detail,
        "opener": item.opener_name or _("someone"),
    }
    texts = {
        Notification.Kind.DISPUTE_OPENED: _("%(who)s opened a dispute on %(label)s: %(detail)s"),
        Notification.Kind.DISPUTE_MESSAGE: _(
            "%(who)s wrote in the dispute on %(label)s: %(detail)s"
        ),
        Notification.Kind.DISPUTE_RESOLVED: _("%(who)s resolved the dispute on %(label)s"),
        Notification.Kind.DISPUTE_CLOSED: _(
            "%(who)s, the Owner, closed %(opener)s’s dispute on %(label)s. Reason: %(detail)s"
        ),
        Notification.Kind.SETTLED: _("%(who)s settled the trip"),
        Notification.Kind.REOPENED: _("%(who)s reopened the trip"),
    }
    return texts[item.kind] % data


def _short(text: str, size: int = 120) -> str:
    text = " ".join(text.split())
    return text if len(text) <= size else text[: size - 1].rstrip() + "…"


# --- The actions ----------------------------------------------------------------------------------


def _locked_dispute(dispute: Dispute) -> Dispute:
    """Lock the trip, then read the dispute fresh, so two taps act once."""
    trip = lock_trip(dispute.trip)
    if trip.is_settled:
        raise DisputeRefused(SETTLED_MESSAGE)
    fresh = Dispute.objects.select_related("expense__payer", "trip").get(pk=dispute.pk)
    fresh.trip = trip
    if not fresh.is_open:
        raise DisputeRefused(
            _("This dispute is resolved, so it takes no new messages.")
            if fresh.state == Dispute.State.RESOLVED
            else _("This dispute is closed, so it takes no new messages.")
        )
    return fresh


def _record(trip, by, action, dispute: Dispute, *, changes=None):
    return history.record(
        trip,
        by,
        action,
        "dispute",
        object_id=dispute.pk,
        label=history.expense_label(dispute.expense),
        changes=changes,
        values={"expense_id": str(dispute.expense_id), "opener": dispute.opened_by_name},
    )


def open_dispute(membership: TripMember, expense: Expense, reason: str) -> Dispute:
    """§5.1. The caller has checked ``may_open`` (403 otherwise)."""
    reason = reason.strip()
    if not reason:
        raise DisputeRefused(_("Write why you disagree with this expense."))
    with transaction.atomic():
        trip = lock_trip(membership.trip)
        if trip.is_settled:
            raise DisputeRefused(SETTLED_MESSAGE)
        if has_open_dispute(membership, expense):
            raise DisputeRefused(_("You already have an open dispute on this expense."))
        user = membership.user
        dispute = Dispute.objects.create(
            trip=trip,
            expense=expense,
            opened_by=user,
            opened_by_name=user.display_name,
            opened_as=membership.linked_traveler.name if membership.linked_traveler else "",
            reason=reason[:500],
        )
        _record(trip, membership, "opened", dispute, changes={"reason": history.change("", reason)})
        notify(
            trip,
            dispute_people(dispute),
            Notification.Kind.DISPUTE_OPENED,
            by=membership,
            label=history.expense_label(expense),
            detail=_short(reason),
            link=expense_link(trip, expense.pk),
        )
    return dispute


def write_message(membership: TripMember, dispute: Dispute, text: str) -> DisputeMessage:
    """§5.2. The caller has checked ``may_write`` (403 otherwise)."""
    text = text.strip()
    if not text:
        raise DisputeRefused(_("Write a message first."))
    with transaction.atomic():
        dispute = _locked_dispute(dispute)
        user = membership.user
        message = DisputeMessage.objects.create(
            dispute=dispute, author=user, author_name=user.display_name, text=text[:1000]
        )
        _record(
            dispute.trip, membership, "message", dispute, changes={"text": history.change("", text)}
        )
        notify(
            dispute.trip,
            dispute_people(dispute),
            Notification.Kind.DISPUTE_MESSAGE,
            by=membership,
            label=history.expense_label(dispute.expense),
            detail=_short(text),
            link=expense_link(dispute.trip, dispute.expense_id),
        )
    return message


def resolve(membership: TripMember, dispute: Dispute) -> None:
    """§5.3: only the opener taps Resolved. The caller has checked ``may_resolve``."""
    with transaction.atomic():
        dispute = _locked_dispute(dispute)
        people = dispute_people(dispute)
        dispute.state = Dispute.State.RESOLVED
        dispute.closed_at = timezone.now()
        dispute.save(update_fields=["state", "closed_at", "updated_at"])
        _record(dispute.trip, membership, "resolved", dispute)
        notify(
            dispute.trip,
            people,
            Notification.Kind.DISPUTE_RESOLVED,
            by=membership,
            label=history.expense_label(dispute.expense),
            link=expense_link(dispute.trip, dispute.expense_id),
        )


def close(membership: TripMember, dispute: Dispute, reason: str) -> None:
    """§5.3: the Owner closes any open dispute, with a required reason. When the Owner paid the
    expense, every account on the trip is notified, so the decision is in the open."""
    reason = reason.strip()
    if not reason:
        raise DisputeRefused(_("Write the reason for closing this dispute."))
    with transaction.atomic():
        dispute = _locked_dispute(dispute)
        trip, expense = dispute.trip, dispute.expense
        people = dispute_people(dispute)
        user = membership.user
        dispute.state = Dispute.State.CLOSED
        dispute.close_reason = reason[:500]
        dispute.closed_by = user
        dispute.closed_by_name = user.display_name
        dispute.closed_at = timezone.now()
        dispute.save(
            update_fields=[
                "state",
                "close_reason",
                "closed_by",
                "closed_by_name",
                "closed_at",
                "updated_at",
            ]
        )
        _record(trip, membership, "closed", dispute, changes={"reason": history.change("", reason)})
        if expense.payer.user_id == user.pk:
            people = _trip_user_ids(trip)
        notify(
            trip,
            people,
            Notification.Kind.DISPUTE_CLOSED,
            by=membership,
            label=history.expense_label(expense),
            detail=_short(reason),
            opener=dispute.opened_by_name,
            link=expense_link(trip, expense.pk),
        )


def open_count_text(count: int) -> str:
    return ngettext("%(n)d open dispute", "%(n)d open disputes", count) % {"n": count}


def disputes_in_use_message(kind: str) -> str:
    """Removing a traveler, a type or a rate is refused while a dispute exists on an expense that
    uses it (spec section 3)."""
    return {
        "traveler": _(
            "This traveler cannot be removed because an expense they are in has a dispute."
        ),
        "type": _("This type cannot be removed because an expense of this type has a dispute."),
        "rate": _("This rate cannot be deleted because an expense in this currency has a dispute."),
    }[kind]
