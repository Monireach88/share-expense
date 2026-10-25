"""Bridge between the database and the pure settlement engine."""

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


def named(trip: Trip, result: SettlementResult) -> dict:
    """Replace participant IDs with participants and category codes with labels, for templates."""
    people = {p.id: p for p in trip.participants.prefetch_related("sponsors")}
    labels = dict(Expense._meta.get_field("category").choices)
    return {
        "total": result.total,
        "currency": result.base_currency,
        "people": [{"person": people[s.participant], "row": s} for s in result.people],
        "transfers": [
            {"sender": people[t.sender], "receiver": people[t.receiver], "amount": t.amount}
            for t in result.transfers
        ],
        "by_category": [
            (labels.get(code, code), amount) for code, amount in result.by_category.items()
        ],
    }
