"""Bridge between the database and the pure settlement engine."""

from decimal import Decimal

from apps.settlement.engine import ExpenseInput, SettlementResult, settle

from .models import Trip


def trip_settlement(trip: Trip) -> SettlementResult:
    participants = list(trip.participants.prefetch_related("sponsors"))
    expenses = trip.expenses.prefetch_related("beneficiaries")
    return settle(
        [p.id for p in participants],
        [
            ExpenseInput(
                payer=e.payer_id,
                beneficiaries=[b.id for b in e.beneficiaries.all()],
                amount=e.amount,
                currency=e.currency,
                category=str(e.category_id),
            )
            for e in expenses
        ],
        base_currency=trip.base_currency,
        rates=trip.rate_map(),
        sponsors={p.id: [s.id for s in p.sponsors.all()] for p in participants if p.sponsors.all()},
    )


def trip_status(trip: Trip, result: SettlementResult | None) -> str:
    """ "settled" once the owner marks it so, "active" once money is spent, otherwise ""."""
    if trip.is_settled:
        return "settled"
    return "active" if result is not None and result.total else ""


def _order(row: dict) -> tuple:
    """Owed (largest first), then owing (largest first), then everyone whose balance is zero."""
    balance = row["row"].balance
    if balance > 0:
        return (0, -balance)
    if balance < 0:
        return (1, balance)
    return (2, 0)


def named(trip: Trip, result: SettlementResult, user=None) -> dict:
    """Replace participant IDs with participants, for templates."""
    people = {p.id: p for p in trip.participants.prefetch_related("sponsors")}
    rows = []
    for s in result.people:
        person = people[s.participant]
        rows.append(
            {
                "person": person,
                "row": s,
                "is_me": bool(user) and person.user_id == user.id,
                "covered_by": list(person.sponsors.all()),
                # (person, amount) for each traveler whose share this one pays.
                "covers": [(people[x], amount) for x, amount in s.covers.items()],
                "covers_total": sum(s.covers.values(), Decimal(0)),
            }
        )
    rows.sort(key=_order)
    me = next((r for r in rows if r["is_me"]), None)
    return {
        "total": result.total,
        "currency": result.base_currency,
        "me": me,
        # The Balances page shows the viewer's own balance in its top card, so the list skips them.
        "others": [r for r in rows if not r["is_me"]] if me and result.total else rows,
        "rows": rows,
    }
