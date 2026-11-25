from contextlib import suppress
from datetime import timedelta
from decimal import Decimal
from itertools import groupby

from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _

from apps.settlement.engine import SettlementError, to_base
from apps.trips.access import get_membership, locked
from apps.trips.offline import cacheable_page
from apps.trips.pagination import DayPage
from apps.trips.summary import named, trip_settlement
from apps.trips.templatetags.ui import format_amount

from .forms import ExpenseForm
from .models import Expense
from .report import ReportFilterForm, build_report, export_rows, to_csv, to_xlsx

MAX_DAY_CHIPS = 14


@cacheable_page
def expense_list(request: HttpRequest, trip_id) -> HttpResponse:
    membership = get_membership(request, trip_id)
    trip = membership.trip
    expenses = list(trip.expenses.select_related("payer").prefetch_related("beneficiaries"))
    rates = trip.rate_map()
    day_totals: dict = {}
    for e in expenses:
        e.base_amount = None
        with suppress(SettlementError):
            e.base_amount = to_base(e.amount, e.currency, trip.base_currency, rates)
        # A day with an unconvertible amount has no total (None), rather than a wrong one.
        if e.base_amount is None or day_totals.get(e.date, 0) is None:
            day_totals[e.date] = None
        else:
            day_totals[e.date] = day_totals.get(e.date, Decimal(0)) + e.base_amount
    page = DayPage(
        request,
        [
            (day, list(items), day_totals[day])
            for day, items in groupby(expenses, key=lambda e: e.date)
        ],
    )
    context = {
        "trip": trip,
        "membership": membership,
        "page": page,
        "days": page.days,
        "multi_year": len({e.date.year for e in expenses}) > 1,
        "people_count": trip.participants.count(),
        "tab": "expenses",
    }
    try:
        context["summary"] = named(trip, trip_settlement(trip), request.user)
    except SettlementError as error:
        context["error"] = str(error)
    else:
        today = timezone.localdate()
        if trip.start_date and _in_trip(trip, today):
            context["today_total"] = day_totals.get(today) or Decimal(0)
    return render(request, "expenses/list.html", context)


def _in_trip(trip, day) -> bool:
    return (not trip.start_date or trip.start_date <= day) and (
        not trip.end_date or day <= trip.end_date
    )


def _initial(request: HttpRequest, trip) -> dict:
    """Sensible defaults: today, the current user as payer, everyone as beneficiary, last currency."""
    last = trip.expenses.filter(created_by=request.user).order_by("-created_at").first()
    me = trip.participants.filter(user=request.user).first()
    today = timezone.localdate()
    return {
        "date": today if _in_trip(trip, today) or not trip.start_date else trip.start_date,
        "payer": me or (last.payer if last else None),
        "beneficiaries": list(trip.participants.all()),
        "currency": last.currency if last else trip.base_currency,
    }


def _trip_days(trip) -> list:
    """Every trip day, for one-tap day chips; empty when the dates are unknown or the trip is long."""
    if not trip.start_date or not trip.end_date or trip.end_date < trip.start_date:
        return []
    count = (trip.end_date - trip.start_date).days + 1
    if count > MAX_DAY_CHIPS:
        return []
    return [trip.start_date + timedelta(days=i) for i in range(count)]


def _form_context(trip, membership, form, expense=None) -> dict:
    participants = list(trip.participants.prefetch_related("sponsors"))
    days = _trip_days(trip)
    return {
        "trip": trip,
        "membership": membership,
        "form": form,
        "expense": expense,
        "trip_days": days,
        "trip_day_isos": [d.isoformat() for d in days],
        "rates": {code: str(rate) for code, rate in trip.rate_map().items()},
        "sponsored": [(p, list(p.sponsors.all())) for p in participants if p.sponsors.all()],
    }


def _saved_text(expense) -> str:
    return _("%(what)s, %(amount)s %(currency)s (%(payer)s paid)") % {
        "what": expense,
        "amount": format_amount(expense.amount, expense.currency),
        "currency": expense.currency,
        "payer": expense.payer.name,
    }


def expense_create(request: HttpRequest, trip_id) -> HttpResponse:
    membership = get_membership(request, trip_id)
    if response := locked(request, membership.trip):
        return response
    trip = membership.trip
    if not trip.participants.exists():
        return redirect("people", trip_id=trip.id)
    form = ExpenseForm(request.POST or None, trip=trip, initial=_initial(request, trip))
    if request.method == "POST" and form.is_valid():
        expense = form.save(commit=False)
        expense.trip = trip
        expense.created_by = expense.updated_by = request.user
        expense.save()
        form.save_m2m()
        messages.success(request, _("Added: %(expense)s") % {"expense": _saved_text(expense)})
        if "add_another" in request.POST:
            return redirect("expense_create", trip_id=trip.id)
        return redirect("trip", trip_id=trip.id)
    return render(request, "expenses/form.html", _form_context(trip, membership, form))


def expense_edit(request: HttpRequest, trip_id, expense_id) -> HttpResponse:
    membership = get_membership(request, trip_id)
    if response := locked(request, membership.trip):
        return response
    expense = get_object_or_404(Expense, pk=expense_id, trip=membership.trip)
    form = ExpenseForm(request.POST or None, instance=expense, trip=membership.trip)
    if request.method == "POST" and form.is_valid():
        expense = form.save(commit=False)
        expense.updated_by = request.user
        expense.save()
        form.save_m2m()
        messages.success(request, _("Saved: %(expense)s") % {"expense": _saved_text(expense)})
        return redirect("trip", trip_id=trip_id)
    return render(
        request, "expenses/form.html", _form_context(membership.trip, membership, form, expense)
    )


def expense_delete(request: HttpRequest, trip_id, expense_id) -> HttpResponse:
    membership = get_membership(request, trip_id)
    if response := locked(request, membership.trip):
        return response
    expense = get_object_or_404(Expense, pk=expense_id, trip=membership.trip)
    if request.method == "POST":
        expense.deleted_at = timezone.now()
        expense.updated_by = request.user
        expense.save(update_fields=["deleted_at", "updated_by", "updated_at"])
        messages.success(request, _("Deleted: %(expense)s") % {"expense": _saved_text(expense)})
        return redirect("trip", trip_id=trip_id)
    return render(
        request,
        "trips/confirm_delete.html",
        {
            "trip": membership.trip,
            "membership": membership,
            "expense": expense,
            "object": str(expense),
            "warning": _("It will be left out of all totals."),
            "button": _("Delete expense"),
            "back": reverse("expense_edit", args=[trip_id, expense.id]),
        },
    )


@cacheable_page
def report(request: HttpRequest, trip_id) -> HttpResponse:
    membership = get_membership(request, trip_id)
    trip = membership.trip
    form = ReportFilterForm(request.GET or None, trip=trip)
    context = {"trip": trip, "membership": membership, "form": form, "tab": "report"}
    try:
        trip_settlement(trip)
    except SettlementError as error:
        context["error"] = str(error)
    data = build_report(trip, form.filters() if request.GET else {})
    page = DayPage(
        request,
        [
            (day, list(rows), None)
            for day, rows in groupby(data["rows"], key=lambda r: r.expense.date)
        ],
    )
    query = request.GET.copy()
    query.pop("page", None)
    context.update(
        report=data,
        page=page,
        filtered=any(form.filters().values()) if request.GET else False,
        export_query=query.urlencode(),
        multi_year=len({r.expense.date.year for r in data["rows"]}) > 1,
        people_count=trip.participants.count(),
    )
    return render(request, "expenses/report.html", context)


def report_export(request: HttpRequest, trip_id, fmt: str) -> HttpResponse:
    membership = get_membership(request, trip_id)
    trip = membership.trip
    form = ReportFilterForm(request.GET or None, trip=trip)
    data = build_report(trip, form.filters() if request.GET else {})
    header, rows = export_rows(trip, data)
    name = slugify(trip.name) or "trip"
    if data["person"]:
        name += f"-{slugify(data['person'].name)}"
    if fmt == "csv":
        response = HttpResponse(to_csv(header, rows), content_type="text/csv; charset=utf-8")
    elif fmt == "xlsx":
        response = HttpResponse(
            to_xlsx(trip.name, header, rows),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        raise Http404
    response["Content-Disposition"] = f'attachment; filename="{name}-expenses.{fmt}"'
    return response
