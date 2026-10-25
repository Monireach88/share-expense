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


def _order(row: dict) -> tuple:
    """Get back (largest first), then owe (largest first), then even, then covered people."""
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
                "pays": [
                    {"person": people[t.receiver], "amount": t.amount}
                    for t in result.transfers
                    if t.sender == s.participant
                ],
                "paid_by": [
                    {"person": people[t.sender], "amount": t.amount}
                    for t in result.transfers
                    if t.receiver == s.participant
                ],
                "for_others": s.paid - s.paid_for_self,
                # Taken from the balance, not from responsible_for, so the two lines of
                # "Why?" always differ by exactly the balance shown after rounding.
                "from_others": s.paid - s.paid_for_self - s.balance,
            }
        )
    rows.sort(key=_order)
    me = next((r for r in rows if r["is_me"]), None)
    if me and me["paid_by"]:
        amounts = {t["amount"] for t in me["paid_by"]}
        me["same_amount"] = amounts.pop() if len(amounts) == 1 else None
        me["payer_names"] = ", ".join(t["person"].name for t in me["paid_by"])
    return {
        "total": result.total,
        "currency": result.base_currency,
        "me": me,
        "rows": rows,
        "payment_count": len(result.transfers),
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
