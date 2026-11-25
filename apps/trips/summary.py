"""Bridge between the database and the pure settlement engine."""

from apps.expenses.models import Expense
from apps.settlement.engine import ExpenseInput, PaymentInput, SettlementResult, settle

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
                category=e.category,
            )
            for e in expenses
        ],
        base_currency=trip.base_currency,
        rates=trip.rate_map(),
        sponsors={p.id: [s.id for s in p.sponsors.all()] for p in participants if p.sponsors.all()},
        payments=[
            PaymentInput(r.sender_id, r.receiver_id, r.amount, r.currency)
            for r in trip.repayments.all()
        ],
    )


def trip_status(result: SettlementResult | None) -> str:
    """ "settled" when money was spent and every balance is zero, "active" otherwise.

    "" when nothing is spent yet or the trip cannot be settled (a missing exchange rate).
    """
    if result is None or result.total == 0:
        return ""
    return "settled" if result.settled else "active"


def _order(row: dict) -> tuple:
    """Owed (largest first), then owing (largest first), then settled, then covered people."""
    balance = row["row"].balance
    if balance > 0:
        return (0, -balance)
    if balance < 0:
        return (1, balance)
    return (3, 0) if row["covered_by"] else (2, 0)


def named(trip: Trip, result: SettlementResult, user=None) -> dict:
    """Replace participant IDs with participants and category codes with labels, for templates."""
    people = {p.id: p for p in trip.participants.prefetch_related("sponsors")}
    labels = dict(Expense._meta.get_field("category").choices)
    largest = max(result.by_category.values(), default=0)
    covers = {pid: [] for pid in people}
    for person in people.values():
        for sponsor in person.sponsors.all():
            covers[sponsor.id].append(person)
    rows = []
    for s in result.people:
        person = people[s.participant]
        rows.append(
            {
                "person": person,
                "row": s,
                "is_me": bool(user) and person.user_id == user.id,
                "covers": covers[person.id],
                "covered_by": list(person.sponsors.all()),
                "for_others": s.paid - s.paid_for_self,
                # Taken from the balance, not from responsible_for, so the lines of the
                # breakdown always add up to exactly the balance shown after rounding.
                "from_others": s.paid - s.paid_for_self - (s.balance - s.sent + s.received),
            }
        )
    rows.sort(key=_order)
    me = next((r for r in rows if r["is_me"]), None)
    return {
        "total": result.total,
        "currency": result.base_currency,
        "me": me,
        "rows": rows,
        "settled": result.settled,
        "by_category": [
            {
                "code": code,
                "label": labels.get(code, code),
                "amount": amount,
                "percent": round(amount * 100 / largest) if largest else 0,
            }
            for code, amount in sorted(result.by_category.items(), key=lambda kv: -kv[1])
        ],
    }
