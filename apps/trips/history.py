"""History: one entry per change to a trip, and Restore for deleted expenses (spec section 3).

``record`` is the only write path. Call it inside the same ``transaction.atomic`` as the change.
Values are stored as names and text (plus ids), so an entry reads correctly after a rename.
"""

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext as _
from django_countries.fields import Country

from apps.expenses.models import Expense
from apps.trips.templatetags.ui import format_amount

from .access import lock_trip
from .models import HistoryEntry, Participant, Trip

# Action keys. The English word is also put into search_text, so "changed" finds those entries.
ACTION_WORDS = {
    "added": "added",
    "changed": "changed",
    "deleted": "deleted",
    "restored": "restored",
    "renamed": "renamed",
    "covered_by": "covered by changed",
    "linked": "linked",
    "unlinked": "unlinked",
    "removed": "removed",
    "role_changed": "role changed",
    "became_owner": "became owner",
    "settled": "settled",
    "reopened": "reopened",
}


def _actor(by):
    """``by`` is a TripMember, a user, or None; returns the user."""
    return getattr(by, "user", by)


def record(
    trip: Trip,
    by,
    action: str,
    object_type: str,
    *,
    object_id="",
    label: str = "",
    changes: dict | None = None,
    values: dict | None = None,
) -> HistoryEntry:
    """Write one History entry. Run it inside the transaction of the change itself."""
    user = _actor(by)
    changes, values = changes or {}, values or {}
    parts = [
        user.display_name if user else "",
        ACTION_WORDS.get(action, action),
        object_type,
        label,
        *_texts(values),
        *(_change_texts(changes)),
    ]
    return HistoryEntry.objects.create(
        trip=trip,
        actor=user,
        actor_name=user.display_name if user else "",
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        object_label=label[:200],
        changes=changes,
        values=values,
        search_text=" ".join(p for p in parts if p).lower(),
    )


def _texts(values: dict) -> list[str]:
    out = []
    for key in ("description", "type", "payer", "currency"):
        out.append(str(values.get(key) or ""))
    out.extend(values.get("for") or [])
    if values.get("amount"):
        out.append(_amount_text(values))
    return out


def _change_texts(changes: dict) -> list[str]:
    out = []
    for change in changes.values():
        out.extend(str(change.get(side) or "") for side in ("old", "new"))
    return out


# --- Expenses ---------------------------------------------------------------------------------


def _day_text(day: date) -> str:
    return f"{day.day} {day:%b} {day.year}"


def _amount_text(values: dict) -> str:
    """The amount as the app writes money everywhere: "4.00 USD", "10,000 KHR"."""
    return f"{format_amount(Decimal(values['amount']), values['currency'])} {values['currency']}"


def expense_snapshot(expense: Expense) -> dict:
    """All the values of an expense, as names and text plus ids. Restore reads these back."""
    beneficiaries = list(expense.beneficiaries.all())
    category = expense.category
    return {
        "date": expense.date.isoformat(),
        "payer": expense.payer.name,
        "payer_id": str(expense.payer_id),
        "for": [p.name for p in beneficiaries],
        "for_ids": [str(p.pk) for p in beneficiaries],
        "type": category.name if category else "",
        "type_id": category.pk if category else None,
        "description": expense.description,
        "amount": f"{expense.amount:f}",
        "currency": expense.currency,
    }


def _people_text(names: list[str], ids: list[str], everyone: set[str] | None) -> str:
    return _("everyone") if everyone is not None and set(ids) == everyone else ", ".join(names)


def expense_changes(before: dict, after: dict, everyone: set[str] | None = None) -> dict:
    """Per changed field: its old and new value as display text (and ids for people and type).
    ``everyone`` holds the ids of all travelers now; a "For" list equal to it reads "everyone"."""
    changes: dict = {}
    if before["date"] != after["date"]:
        changes["date"] = {
            "old": _day_text(date.fromisoformat(before["date"])),
            "new": _day_text(date.fromisoformat(after["date"])),
        }
    if before["payer_id"] != after["payer_id"]:
        changes["payer"] = {
            "old": before["payer"],
            "new": after["payer"],
            "old_id": before["payer_id"],
            "new_id": after["payer_id"],
        }
    if set(before["for_ids"]) != set(after["for_ids"]):
        changes["for"] = {
            "old": _people_text(before["for"], before["for_ids"], everyone),
            "new": _people_text(after["for"], after["for_ids"], everyone),
            "old_ids": before["for_ids"],
            "new_ids": after["for_ids"],
        }
    if before["type_id"] != after["type_id"]:
        changes["type"] = {
            "old": before["type"],
            "new": after["type"],
            "old_id": before["type_id"],
            "new_id": after["type_id"],
        }
    if before["description"] != after["description"]:
        changes["description"] = {"old": before["description"], "new": after["description"]}
    if Decimal(before["amount"]) != Decimal(after["amount"]):
        changes["amount"] = {"old": _amount_text(before), "new": _amount_text(after)}
    if before["currency"] != after["currency"]:
        changes["currency"] = {"old": before["currency"], "new": after["currency"]}
    return changes


def fresh_expense(expense_id) -> Expense:
    """The expense as the database holds it now, with what a snapshot needs."""
    return (
        Expense.all_objects.select_related("payer", "category")
        .prefetch_related("beneficiaries")
        .get(pk=expense_id)
    )


def expense_label(expense: Expense) -> str:
    return str(expense) or _("expense")


def record_expense(trip, by, action, expense, *, before: dict | None = None) -> HistoryEntry | None:
    """Write the entry of an expense action; ``before`` is the snapshot taken before a change.
    A save that changes nothing writes no entry."""
    after = expense_snapshot(expense)
    everyone = {str(pk) for pk in trip.participants.values_list("pk", flat=True)}
    changes = expense_changes(before, after, everyone) if action == "changed" and before else {}
    if action == "changed" and not changes:
        return None
    return record(
        trip,
        by,
        action,
        "expense",
        object_id=expense.pk,
        label=expense_label(expense),
        changes=changes,
        values=after,
    )


# --- Restore ----------------------------------------------------------------------------------


def last_expense_values(trip: Trip, expense_id, row: Expense | None = None) -> dict | None:
    """The values History last shows for an expense; for one deleted before History existed,
    the values of its row. None when there is neither."""
    entry = trip.history.filter(object_type="expense", object_id=str(expense_id)).first()
    if entry and entry.values:
        return entry.values
    return expense_snapshot(fresh_expense(row.pk)) if row is not None else None


class RestoreRefused(Exception):
    """Restore cannot happen now; the message says what to fix first."""


def _resolve(values: dict, trip: Trip):
    """Match the stored payer, "For" travelers and type to what exists now: by id, else by name
    (a person or type added again after its removal is the same one to the reader).
    Returns (payer, beneficiaries, category, problems)."""
    people = {str(p.pk): p for p in trip.participants.all()}
    by_name = {p.name.casefold(): p for p in people.values()}
    problems = []
    missing: set[str] = set()

    def person(pk, name):
        found = people.get(str(pk)) or by_name.get(name.casefold())
        if found is None and name not in missing:
            missing.add(name)
            problems.append(_("traveler %(name)s") % {"name": name})
        return found

    payer = person(values["payer_id"], values["payer"])
    beneficiaries = [
        person(pk, name) for pk, name in zip(values["for_ids"], values["for"], strict=True)
    ]
    category = None
    if values.get("type"):
        category = trip.categories.filter(pk=values["type_id"]).first() or (
            trip.categories.filter(name__iexact=values["type"]).first()
        )
        if category is None:
            problems.append(_("type %(name)s") % {"name": values["type"]})
    if values["currency"] not in trip.currencies():
        problems.append(_("the %(currency)s rate") % {"currency": values["currency"]})
    return payer, [b for b in beneficiaries if b], category, problems


def restore_expense(trip: Trip, expense_id, *, by) -> bool:
    """Bring a deleted expense back with the values History last shows.

    Returns False when it was already restored (a second tap does nothing). Raises
    RestoreRefused with a message that names what is missing. The caller has checked the role
    and the settled state; this runs under the trip lock, so a double tap restores once.
    """
    with transaction.atomic():
        lock_trip(trip)
        expense = Expense.all_objects.filter(pk=expense_id, trip=trip).select_for_update().first()
        if expense is None:
            raise RestoreRefused(_("This expense can no longer be restored."))
        if expense.deleted_at is None:
            return False
        values = last_expense_values(trip, expense_id, expense)
        payer, beneficiaries, category, problems = _resolve(values, trip)
        if problems:
            raise RestoreRefused(
                _("Not restored. Add these first: %(problems)s.")
                % {"problems": ", ".join(problems)}
            )
        expense.date = date.fromisoformat(values["date"])
        expense.payer = payer
        expense.category = category
        expense.description = values["description"]
        expense.amount = Decimal(values["amount"])
        expense.currency = values["currency"]
        expense.deleted_at = None
        expense.updated_by = _actor(by)
        expense.save()
        expense.beneficiaries.set(beneficiaries)
        record_expense(trip, by, "restored", fresh_expense(expense.pk))
        return True


# --- The lines of the History page -------------------------------------------------------------


def changes_text(changes: dict) -> str:
    labels = {
        "date": _("date"),
        "payer": _("paid by"),
        "for": _("split between"),
        "type": _("type"),
        "description": _("description"),
        "amount": _("amount"),
        "currency": _("currency"),
    }
    return "; ".join(
        f"{labels.get(field, field)} {c.get('old') or '–'} → {c.get('new') or '–'}"
        for field, c in changes.items()
    )


def describe(entry: HistoryEntry) -> str:
    """The entry as one sentence in the reader's language: "Cara changed Dinner: amount 40 USD
    → 4 USD". Built from the stored names and values, never from live rows."""
    who = entry.actor_name or _("Someone")
    label = entry.object_label
    kind, action, changes = entry.object_type, entry.action, entry.changes
    if kind == "expense":
        label = f"“{label}”"
    old = new = ""
    if changes:
        first = next(iter(changes.values()))
        old, new = first.get("old") or "", first.get("new") or ""
    data = {"who": who, "label": label, "old": old, "new": new}
    if kind == "expense":
        if action == "changed":
            return _("%(who)s changed %(label)s: %(changes)s") % {
                **data,
                "changes": changes_text(changes),
            }
        summary = ""
        if entry.values:
            summary = _("%(amount)s, paid by %(payer)s") % {
                "amount": _amount_text(entry.values),
                "payer": entry.values["payer"],
            }
        verbs = {
            "added": _("%(who)s added %(label)s"),
            "deleted": _("%(who)s deleted %(label)s"),
            "restored": _("%(who)s restored %(label)s"),
        }
        text = verbs[action] % data
        return f"{text}: {summary}" if summary else text
    texts = {
        ("traveler", "added"): _("%(who)s added traveler %(label)s"),
        ("traveler", "renamed"): _("%(who)s renamed traveler %(old)s → %(new)s"),
        ("traveler", "covered_by"): _("%(who)s changed who covers %(label)s: %(old)s → %(new)s"),
        ("traveler", "linked"): _("%(who)s linked traveler %(label)s to account %(new)s"),
        ("traveler", "unlinked"): _("%(who)s unlinked traveler %(label)s from account %(old)s"),
        ("traveler", "removed"): _("%(who)s removed traveler %(label)s"),
        ("account", "added"): _("%(who)s added %(label)s's account"),
        ("account", "role_changed"): _("%(who)s changed %(label)s's role: %(old)s → %(new)s"),
        ("account", "removed"): _("%(who)s removed %(label)s's account"),
        ("account", "became_owner"): _("%(who)s made %(label)s the Owner"),
        ("rate", "added"): _("%(who)s added the %(label)s rate: %(new)s"),
        ("rate", "changed"): _("%(who)s changed the %(label)s rate: %(old)s → %(new)s"),
        ("rate", "removed"): _("%(who)s removed the %(label)s rate: %(old)s"),
        ("type", "added"): _("%(who)s added type %(label)s"),
        ("type", "renamed"): _("%(who)s renamed type %(old)s → %(new)s"),
        ("type", "changed"): _("%(who)s changed type %(label)s: icon %(old)s → %(new)s"),
        ("type", "removed"): _("%(who)s removed type %(label)s"),
        ("trip", "settled"): _("%(who)s settled the trip"),
        ("trip", "reopened"): _("%(who)s reopened the trip"),
        ("trip", "renamed"): _("%(who)s renamed the trip: %(old)s → %(new)s"),
    }
    if (kind, action) in texts:
        return texts[(kind, action)] % data
    if kind == "trip" and action == "changed":
        return _("%(who)s changed the trip settings: %(changes)s") % {
            **data,
            "changes": "; ".join(
                f"{c.get('label', field)} {c.get('old') or '–'} → {c.get('new') or '–'}"
                for field, c in changes.items()
            ),
        }
    return f"{who} {ACTION_WORDS.get(action, action)} {kind} {label}".strip()


# --- Travelers, rates and trip: the old and new values of one change ----------------------------


def change(old, new, **ids) -> dict:
    return {"old": old, "new": new, **ids}


def rate_line(trip: Trip, currency: str, rate: Decimal) -> str:
    """The rate with its units, as the Settings page shows it: "1 USD = 4,100 KHR"."""
    return f"1 {trip.base_currency} = {rate_text(rate)} {currency}"


def setting_text(field: str, value) -> str:
    """A trip setting as text: country name, date as "1 Jun 2026", else the value."""
    if not value:
        return ""
    if field == "country":
        return Country(str(value)).name
    if isinstance(value, date):
        return _day_text(value)
    return str(value)


def rate_text(rate: Decimal) -> str:
    """25000.000000 -> "25,000"; 0.039000 -> "0.039"."""
    text = f"{rate:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    whole, _dot, fraction = text.partition(".")
    return f"{int(whole):,}" + (f".{fraction}" if fraction else "")


def traveler_state(participant: Participant) -> dict:
    """The traveler's name, covered-by list and linked account, taken before an edit."""
    sponsors = list(participant.sponsors.all()) if participant.pk else []
    user = participant.user if participant.user_id else None
    return {
        "name": participant.name,
        "covered_by": [s.name for s in sponsors],
        "covered_by_ids": sorted(str(s.pk) for s in sponsors),
        "account": user.display_name if user else "",
        "account_id": user.pk if user else None,
    }


def record_traveler_changes(trip: Trip, by, participant: Participant, before: dict | None) -> None:
    """Write one entry per kind of change: added, renamed, covered-by changed, linked, unlinked."""
    after = traveler_state(participant)
    pid = participant.pk
    if before is None:
        record(trip, by, "added", "traveler", object_id=pid, label=after["name"])
        before = {
            "name": after["name"],
            "covered_by": [],
            "covered_by_ids": [],
            "account": "",
            "account_id": None,
        }
    if before["name"] != after["name"]:
        record(
            trip,
            by,
            "renamed",
            "traveler",
            object_id=pid,
            label=after["name"],
            changes={"name": change(before["name"], after["name"])},
        )
    if before["covered_by_ids"] != after["covered_by_ids"]:
        record(
            trip,
            by,
            "covered_by",
            "traveler",
            object_id=pid,
            label=after["name"],
            changes={
                "covered_by": change(
                    ", ".join(before["covered_by"]) or _("nobody"),
                    ", ".join(after["covered_by"]) or _("nobody"),
                )
            },
        )
    if before["account_id"] != after["account_id"]:
        if before["account_id"] is not None:
            record(
                trip,
                by,
                "unlinked",
                "traveler",
                object_id=pid,
                label=after["name"],
                changes={"account": change(before["account"], "")},
            )
        if after["account_id"] is not None:
            record(
                trip,
                by,
                "linked",
                "traveler",
                object_id=pid,
                label=after["name"],
                changes={"account": change("", after["account"])},
            )
