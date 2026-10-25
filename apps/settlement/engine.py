"""Settlement engine: who spent what, and who must pay whom.

Pure Python with no database access, so it can be tested alone and moved
into its own service later. It reproduces the rules of the owner's original
spreadsheet:

1. Every expense is converted to the trip's base currency with one fixed rate
   per currency (1 base unit = ``rate`` foreign units), rounded to cents.
2. The converted amount is split equally among the expense's beneficiaries.
3. A participant may be covered by one or more sponsors. Their share then
   moves to the sponsors, split equally. No sponsor means self-covered.
4. balance = amount paid - shares this participant is responsible for.
   Positive: the group owes them. Negative: they owe the group.

Shares are kept as exact fractions until the end, then rounded to whole
cents so that all balances add up to exactly zero.
"""

from collections import defaultdict
from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

CENT = Decimal("0.01")

type ParticipantId = Hashable


class SettlementError(ValueError):
    """The trip data cannot be settled (unknown person, missing rate, ...)."""


@dataclass(frozen=True)
class ExpenseInput:
    payer: ParticipantId
    beneficiaries: Sequence[ParticipantId]
    amount: Decimal
    currency: str
    category: str = ""


@dataclass(frozen=True)
class Transfer:
    sender: ParticipantId
    receiver: ParticipantId
    amount: Decimal


@dataclass
class PersonSummary:
    participant: ParticipantId
    paid: Decimal = Decimal("0.00")
    own_share: Decimal = Decimal("0.00")
    responsible_for: Decimal = Decimal("0.00")
    balance: Decimal = Decimal("0.00")


@dataclass
class SettlementResult:
    base_currency: str
    total: Decimal
    people: list[PersonSummary]
    by_category: dict[str, Decimal]
    transfers: list[Transfer] = field(default_factory=list)


def to_base(
    amount: Decimal, currency: str, base_currency: str, rates: Mapping[str, Decimal]
) -> Decimal:
    """Convert ``amount`` to the base currency, rounded to cents like the spreadsheet."""
    if currency == base_currency:
        return amount.quantize(CENT, ROUND_HALF_UP)
    rate = rates.get(currency)
    if rate is None or rate <= 0:
        raise SettlementError(f"No exchange rate for {currency}")
    return (amount / rate).quantize(CENT, ROUND_HALF_UP)


def _to_cents(value: Fraction) -> int:
    """Round a fraction of cents half away from zero."""
    sign = -1 if value < 0 else 1
    return sign * int(abs(value) + Fraction(1, 2))


def _round_preserving_sum(values: Mapping[ParticipantId, Fraction]) -> dict[ParticipantId, int]:
    """Round each value to whole cents so the rounded values keep the exact total.

    Largest remainder method: floor everything, then give the missing cents to
    the values that lost the most in rounding.
    """
    floors = {key: value.numerator // value.denominator for key, value in values.items()}
    target = _to_cents(sum(values.values(), Fraction(0)))
    missing = target - sum(floors.values())
    by_remainder = sorted(values, key=lambda key: values[key] - floors[key], reverse=True)
    for key in by_remainder[:missing]:
        floors[key] += 1
    return floors


def _cents(value: int) -> Decimal:
    return (Decimal(value) / 100).quantize(CENT)


def suggest_transfers(balances: Mapping[ParticipantId, Decimal]) -> list[Transfer]:
    """Greedy plan: the biggest debtor pays the biggest creditor until all are even.

    Gives at most (number of people - 1) transfers.
    """
    debtors = [[p, -b] for p, b in balances.items() if b < 0]
    creditors = [[p, b] for p, b in balances.items() if b > 0]
    debtors.sort(key=lambda item: item[1], reverse=True)
    creditors.sort(key=lambda item: item[1], reverse=True)
    transfers: list[Transfer] = []
    d = c = 0
    while d < len(debtors) and c < len(creditors):
        amount = min(debtors[d][1], creditors[c][1])
        if amount > 0:
            transfers.append(Transfer(debtors[d][0], creditors[c][0], amount))
        debtors[d][1] -= amount
        creditors[c][1] -= amount
        if debtors[d][1] == 0:
            d += 1
        if creditors[c][1] == 0:
            c += 1
    return transfers


def settle(
    participants: Sequence[ParticipantId],
    expenses: Iterable[ExpenseInput],
    *,
    base_currency: str,
    rates: Mapping[str, Decimal] | None = None,
    sponsors: Mapping[ParticipantId, Sequence[ParticipantId]] | None = None,
) -> SettlementResult:
    """Compute every participant's totals, balance, and the transfers that settle the trip.

    ``sponsors`` maps a participant to the people who cover their share. A
    sponsor must cover themselves (no chains), so every share ends with
    exactly one layer of sponsors.
    """
    rates = rates or {}
    sponsors = sponsors or {}
    known = set(participants)
    if len(known) != len(participants):
        raise SettlementError("Participants must be unique")

    covered_by: dict[ParticipantId, list[ParticipantId]] = {}
    for person in participants:
        payers = list(dict.fromkeys(sponsors.get(person) or [person]))
        for sponsor in payers:
            if sponsor not in known:
                raise SettlementError(f"Unknown sponsor {sponsor!r}")
            if sponsor != person and any(s != sponsor for s in sponsors.get(sponsor) or [sponsor]):
                raise SettlementError(f"Sponsor {sponsor!r} is covered by someone else")
        covered_by[person] = payers

    paid: dict[ParticipantId, Fraction] = defaultdict(Fraction)
    own: dict[ParticipantId, Fraction] = defaultdict(Fraction)
    by_category: dict[str, Fraction] = defaultdict(Fraction)
    total = Fraction(0)

    for expense in expenses:
        beneficiaries = list(dict.fromkeys(expense.beneficiaries))
        if expense.payer not in known:
            raise SettlementError(f"Unknown payer {expense.payer!r}")
        if not beneficiaries:
            raise SettlementError("An expense needs at least one beneficiary")
        unknown = [b for b in beneficiaries if b not in known]
        if unknown:
            raise SettlementError(f"Unknown beneficiary {unknown[0]!r}")
        cents = Fraction(to_base(expense.amount, expense.currency, base_currency, rates) * 100)
        paid[expense.payer] += cents
        by_category[expense.category] += cents
        total += cents
        for person in beneficiaries:
            own[person] += cents / len(beneficiaries)

    responsible: dict[ParticipantId, Fraction] = defaultdict(Fraction)
    for person in participants:
        payers = covered_by[person]
        for sponsor in payers:
            responsible[sponsor] += own[person] / len(payers)

    exact_balances = {p: paid[p] - responsible[p] for p in participants}
    balances = {p: _cents(c) for p, c in _round_preserving_sum(exact_balances).items()}

    people = [
        PersonSummary(
            participant=p,
            paid=_cents(_to_cents(paid[p])),
            own_share=_cents(_to_cents(own[p])),
            responsible_for=_cents(_to_cents(responsible[p])),
            balance=balances[p],
        )
        for p in participants
    ]
    return SettlementResult(
        base_currency=base_currency,
        total=_cents(_to_cents(total)),
        people=people,
        by_category={
            k: _cents(_to_cents(v)) for k, v in sorted(by_category.items(), key=lambda kv: -kv[1])
        },
        transfers=suggest_transfers(balances),
    )
