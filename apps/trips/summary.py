"""Bridge between the database and the pure settlement engine."""

from decimal import Decimal

from apps.expenses.models import Expense
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
                category=e.category,
            )
            for e in expenses
        ],
        base_currency=trip.base_currency,
        rates=trip.rate_map(),
        sponsors={p.id: [s.id for s in p.sponsors.all()] for p in participants if p.sponsors.all()},
    )


def my_balance(trip: Trip, result: SettlementResult, user) -> Decimal | None:
    """The balance of the traveller linked to ``user``, or None if no traveller is linked."""
    me = trip.participants.filter(user=user).values_list("id", flat=True).first()
    return next((s.balance for s in result.people if s.participant == me), None)


def named(trip: Trip, result: SettlementResult, user=None) -> dict:
    """Replace participant IDs with participants and category codes with labels, for templates."""
    people = {p.id: p for p in trip.participants.prefetch_related("sponsors")}
    labels = dict(Expense._meta.get_field("category").choices)
    largest = max(result.by_category.values(), default=0)
    return {
        "total": result.total,
        "currency": result.base_currency,
        "people": [
            {
                "person": people[s.participant],
                "row": s,
                "is_me": people[s.participant].user_id == user.id if user else False,
            }
            for s in result.people
        ],
        "transfers": [
            {
                "sender": people[t.sender],
                "receiver": people[t.receiver],
                "amount": t.amount,
                "is_me": bool(user)
                and user.id in (people[t.sender].user_id, people[t.receiver].user_id),
            }
            for t in result.transfers
        ],
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
