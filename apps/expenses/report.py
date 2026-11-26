"""The Report page: filter a trip's expenses, total them, and export the result.

Amounts are converted to the trip's base currency with the trip's fixed rates, the same way the
settlement engine does. A person's share of an expense follows the engine's rules too: the amount
is split equally among the people it was for, and the part of a covered person goes to the people
who cover them.
"""

import csv
import io
from collections import defaultdict
from contextlib import suppress
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction

from django import forms
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.settlement.engine import SettlementError, _to_cents, to_base
from apps.trips.forms import DATE_INPUT
from apps.trips.models import Participant, Trip
from apps.trips.summary import trip_settlement
from apps.trips.templatetags.ui import WHOLE_UNIT_CURRENCIES

from .models import Category, Expense


class ReportFilterForm(forms.Form):
    person = forms.ModelChoiceField(
        label=gettext_lazy("Traveler"),
        queryset=Participant.objects.none(),
        required=False,
        empty_label=gettext_lazy("Everyone"),
    )
    category = forms.ModelChoiceField(
        label=gettext_lazy("Type"),
        queryset=Category.objects.none(),
        required=False,
        empty_label=gettext_lazy("All types"),
    )
    start = forms.DateField(label=gettext_lazy("From"), required=False, widget=DATE_INPUT)
    end = forms.DateField(label=gettext_lazy("To"), required=False, widget=DATE_INPUT)

    def __init__(self, data, *, trip: Trip):
        super().__init__(data)
        # Only this trip's people, so an ID from another trip is rejected as invalid.
        self.fields["person"].queryset = trip.participants.all()
        self.fields["category"].queryset = trip.categories.all()

    def filters(self) -> dict:
        """The valid filters; an invalid value is ignored rather than failing the page."""
        self.is_valid()
        return {
            name: self.cleaned_data.get(name) for name in self.fields if name not in self.errors
        }


@dataclass
class ReportRow:
    expense: Expense
    base_amount: Decimal
    share: (
        Decimal | None
    )  # The filtered person's share in the base currency; None without a person.
    # The same share in the expense's own currency, for the row's card (no conversion needed).
    share_local: Decimal | None = None


def _shares(trip: Trip) -> dict:
    """For each participant, the people who pay their share (themselves if nobody covers them)."""
    people = trip.participants.prefetch_related("sponsors")
    return {p.id: [s.id for s in p.sponsors.all()] or [p.id] for p in people}


def _share_of(person_id, expense: Expense, base: Decimal, covered_by: dict) -> Fraction:
    people = [b.id for b in expense.beneficiaries.all()]
    share = Fraction(0)
    for beneficiary in people:
        payers = covered_by.get(beneficiary, [beneficiary])
        if person_id in payers:
            share += Fraction(base) / len(people) / len(payers)
    return share


def _bars(values: dict) -> dict:
    """Each amount (already in cents, so sums need no rounding) and its bar width."""
    largest = max(values.values(), default=0)
    return {
        key: {"amount": value, "percent": round(value * 100 / largest) if largest else 0}
        for key, value in values.items()
    }


def _round_to(exact: list[Fraction], target_cents: int) -> list[Decimal]:
    """Round each value to cents so the results add up to ``target_cents`` exactly.

    Largest remainder method, like the settlement engine: floor everything, then give the
    missing cents to the values that lost the most.
    """
    cents = [value * 100 for value in exact]
    floors = [c.numerator // c.denominator for c in cents]
    order = sorted(range(len(cents)), key=lambda i: cents[i] - floors[i], reverse=True)
    for i in order[: max(0, target_cents - sum(floors))]:
        floors[i] += 1
    return [Decimal(f) / 100 for f in floors]


def _local_share(expense: Expense, base: Decimal, exact: Fraction) -> Decimal:
    """The person's part of the expense in its own currency: amount × (share ÷ amount in base)."""
    if not base:
        return Decimal(0)
    value = Fraction(expense.amount) * exact / Fraction(base)
    places = 0 if expense.currency in WHOLE_UNIT_CURRENCIES else 2
    cents = _to_cents(value * 10**places)
    return Decimal(cents).scaleb(-places)


def build_report(trip: Trip, filters: dict) -> dict:
    """Filtered rows (newest first) and their totals by type and by day, in the base currency."""
    person: Participant | None = filters.get("person")
    expenses = trip.expenses.select_related("payer", "category").prefetch_related("beneficiaries")
    if filters.get("category"):
        expenses = expenses.filter(category=filters["category"])
    if filters.get("start"):
        expenses = expenses.filter(date__gte=filters["start"])
    if filters.get("end"):
        expenses = expenses.filter(date__lte=filters["end"])

    rates = trip.rate_map()
    covered_by = _shares(trip) if person else {}
    rows: list[ReportRow] = []
    exact_shares: list[Fraction] = []
    total = paid = Decimal(0)
    for expense in expenses:
        try:
            base = to_base(expense.amount, expense.currency, trip.base_currency, rates)
        except SettlementError:
            continue  # The page shows the missing rate; the row cannot be totalled without it.
        if person:
            exact = _share_of(person.id, expense, base, covered_by)
            involved = expense.payer_id == person.id or any(
                b.id == person.id for b in expense.beneficiaries.all()
            )
            if not exact and not involved:
                continue
            exact_shares.append(exact)
            if expense.payer_id == person.id:
                paid += base
        expense.base_amount = base
        rows.append(ReportRow(expense, base, None))
        total += base

    if person:
        # The rows' shares are rounded together so they add up to the person's share; without
        # other filters that is the Balances page's number, so both pages always agree.
        target = _to_cents(sum(exact_shares, Fraction(0)) * 100)
        if not any(filters.get(k) for k in ("category", "start", "end")):
            with suppress(SettlementError, StopIteration):
                result = trip_settlement(trip)
                share = next(p for p in result.people if p.participant == person.id)
                target = int(share.responsible_for * 100)
        for row, share, exact in zip(
            rows, _round_to(exact_shares, target), exact_shares, strict=True
        ):
            row.share = share
            row.share_local = _local_share(row.expense, row.base_amount, exact)

    by_category: dict[Category | None, Decimal] = defaultdict(Decimal)
    by_day: dict[date, Decimal] = defaultdict(Decimal)
    for row in rows:
        counted = row.share if person else row.base_amount
        if counted:
            by_category[row.expense.category] += counted
            by_day[row.expense.date] += counted

    type_bars, day_bars = _bars(by_category), _bars(by_day)
    return {
        "person": person,
        "rows": rows,
        "total": total,
        "paid": paid,
        "share": sum((r.share for r in rows), Decimal(0)) if person else None,
        "covered_by": list(person.sponsors.all()) if person else [],
        # With a traveler chosen, every card shows their share, also when someone covers them
        # (it is then 0, and the cards they paid show "Paid <amount>").
        "show_share": bool(person),
        "by_category": [
            {"category": category, **type_bars[category]}
            for category, _amount in sorted(by_category.items(), key=lambda kv: -kv[1])
        ],
        "by_day": [{"day": day, **day_bars[day]} for day in sorted(by_day)],
        "covers": list(person.sponsored.all()) if person else [],
    }


def export_rows(trip: Trip, report: dict) -> tuple[list[str], list[list]]:
    """Header and rows for CSV and Excel: one line per expense, oldest first, like the sheet."""
    base = trip.base_currency
    header = [
        _("Date"),
        _("Description"),
        _("Type"),
        _("Paid by"),
        _("Split between"),
        _("Amount"),
        _("Currency"),
        _("Amount in %(base)s") % {"base": base},
    ]
    person = report["person"]
    if person:
        header.append(_("%(name)s's share in %(base)s") % {"name": person.name, "base": base})
    rows = []
    for row in reversed(report["rows"]):
        e = row.expense
        line = [
            e.date,
            e.description,
            e.category.name if e.category else "",
            e.payer.name,
            ", ".join(b.name for b in e.beneficiaries.all()),
            e.amount,
            e.currency,
            row.base_amount,
        ]
        if person:
            line.append(row.share)
        rows.append(line)
    return header, rows


def to_csv(header: list[str], rows: list[list]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows([[v.isoformat() if isinstance(v, date) else v for v in r] for r in rows])
    # The byte order mark makes Excel open the file as UTF-8, so names with accents survive.
    return ("﻿" + out.getvalue()).encode()


def to_xlsx(title: str, header: list[str], rows: list[list]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    book = Workbook()
    sheet = book.active
    sheet.title = title[:31] or "Expenses"
    sheet.append(header)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append(row)
    money = [i for i, name in enumerate(header, 1) if i >= 6 and i != 7]
    for column in money:
        for (cell,) in sheet.iter_rows(min_row=2, min_col=column, max_col=column):
            cell.number_format = "#,##0.00"
    for (cell,) in sheet.iter_rows(min_row=2, min_col=1, max_col=1):
        cell.number_format = "yyyy-mm-dd"
    widths = [12, 32, 18, 16, 32, 14, 10, 16, 18]
    for i, width in enumerate(widths[: len(header)], 1):
        sheet.column_dimensions[get_column_letter(i)].width = width
    sheet.freeze_panes = "A2"
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()
