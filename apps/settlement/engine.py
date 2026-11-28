"""Settlement engine: who spent what, and who must pay whom.

Pure Python with no database access, so it can be tested alone and moved
into its own service later. It reproduces the rules of the owner's original
spreadsheet:

1. Every expense is converted to the trip's base currency with one fixed rate
   per currency (1 base unit = ``rate`` foreign units), rounded to cents.
2. The converted amount is split equally among the expense's beneficiaries.
3. A participant may be covered by one or more sponsors. Their share then
   moves to the sponsors, split equally. No sponsor means self-covered.
4. balance = paid - own share + share covered by sponsors - shares covered for others.
   Positive: the group owes them. Negative: they owe the group.

Shares are kept as exact fractions until the end, then rounded to whole
cents so that all balances add up to exactly zero.
"""

from collections import defaultdict
from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

from django.utils.translation import gettext as _

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
    # The part of ``paid`` that covered this person's own ``responsible_for``. The rest of
    # ``paid`` was for others, and the rest of ``responsible_for`` others paid for them.
    paid_for_self: Decimal = Decimal("0.00")
    # Covering, rounded so that on every row: paid - own_share + covered - sum(covers) = balance.
    covered: Decimal = Decimal("0.00")  # The own share that sponsors pay for this person.
    covers: dict = field(default_factory=dict)  # Covered person -> the part this person pays.


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
        raise SettlementError(_("No exchange rate for %(currency)s") % {"currency": currency})
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
        raise SettlementError(_("Travelers must be unique."))

    covered_by: dict[ParticipantId, list[ParticipantId]] = {}
    for person in participants:
        payers = list(dict.fromkeys(sponsors.get(person) or [person]))
        for sponsor in payers:
            if sponsor not in known:
                raise SettlementError(_("Unknown sponsor %(name)s") % {"name": sponsor})
            if sponsor != person and any(s != sponsor for s in sponsors.get(sponsor) or [sponsor]):
                raise SettlementError(
                    _("Sponsor %(name)s is covered by someone else") % {"name": sponsor}
                )
        covered_by[person] = payers

    paid: dict[ParticipantId, Fraction] = defaultdict(Fraction)
    own: dict[ParticipantId, Fraction] = defaultdict(Fraction)
    paid_for_self: dict[ParticipantId, Fraction] = defaultdict(Fraction)
    by_category: dict[str, Fraction] = defaultdict(Fraction)
    total = Fraction(0)

    for expense in expenses:
        beneficiaries = list(dict.fromkeys(expense.beneficiaries))
        if expense.payer not in known:
            raise SettlementError(_("Unknown payer %(name)s") % {"name": expense.payer})
        if not beneficiaries:
            raise SettlementError(_("An expense needs at least one beneficiary"))
        unknown = [b for b in beneficiaries if b not in known]
        if unknown:
            raise SettlementError(_("Unknown beneficiary %(name)s") % {"name": unknown[0]})
        cents = Fraction(to_base(expense.amount, expense.currency, base_currency, rates) * 100)
        paid[expense.payer] += cents
        by_category[expense.category] += cents
        total += cents
        for person in beneficiaries:
            own[person] += cents / len(beneficiaries)
            payers = covered_by[person]
            if expense.payer in payers:
                paid_for_self[expense.payer] += cents / len(beneficiaries) / len(payers)

    responsible: dict[ParticipantId, Fraction] = defaultdict(Fraction)
    for person in participants:
        payers = covered_by[person]
        for sponsor in payers:
            responsible[sponsor] += own[person] / len(payers)

    exact_balances = {p: paid[p] - responsible[p] for p in participants}
    balances = {p: _cents(c) for p, c in _round_preserving_sum(exact_balances).items()}

    # A covered person's share is rounded once; its parts for each sponsor are rounded so
    # they add up to it exactly (152.98 split by 3 is 50.99 + 50.99 + 51.00).
    covers: dict[ParticipantId, dict[ParticipantId, int]] = defaultdict(dict)
    covered_cents: dict[ParticipantId, int] = {}
    for person in participants:
        payers = covered_by[person]
        if payers == [person]:
            continue
        covered_cents[person] = _to_cents(own[person])
        parts = _round_preserving_sum(
            {sponsor: Fraction(covered_cents[person], len(payers)) for sponsor in payers}
        )
        for sponsor, cents in parts.items():
            covers[sponsor][person] = cents

    people = []
    for p in participants:
        person = PersonSummary(
            participant=p,
            paid=_cents(_to_cents(paid[p])),
            balance=balances[p],
            paid_for_self=_cents(_to_cents(paid_for_self[p])),
            covers={x: _cents(c) for x, c in covers[p].items()},
        )
        # Taken from the rounded balance, not rounded on its own, so that on every row
        # paid - share = balance, and all shares add up to the total.
        person.responsible_for = person.paid - person.balance
        if p in covered_cents:
            person.own_share = person.covered = _cents(covered_cents[p])
        else:
            person.own_share = person.responsible_for - sum(person.covers.values(), Decimal(0))
        people.append(person)
    return SettlementResult(
        base_currency=base_currency,
        total=_cents(_to_cents(total)),
        people=people,
        by_category={
            k: _cents(_to_cents(v)) for k, v in sorted(by_category.items(), key=lambda kv: -kv[1])
        },
        transfers=suggest_transfers(balances),
    )
