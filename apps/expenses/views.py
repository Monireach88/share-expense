from contextlib import suppress
from datetime import date, timedelta
from decimal import Decimal
from itertools import groupby

from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.settlement.engine import SettlementError, to_base
from apps.trips.access import get_membership, locked
from apps.trips.offline import cacheable_page
from apps.trips.pagination import DayPage
from apps.trips.summary import named, trip_settlement
from apps.trips.templatetags.ui import format_amount

from .forms import ExpenseForm
from .models import Category, Expense
from .report import ReportFilterForm, build_report, export_rows, to_csv, to_xlsx

MAX_DAY_CHIPS = 14


@cacheable_page
def expense_list(request: HttpRequest, trip_id) -> HttpResponse:
    membership = get_membership(request, trip_id)
    trip = membership.trip
    expenses = list(trip.expenses.select_related("payer").prefetch_related("beneficiaries"))
    q = request.GET.get("q", "").strip()[:100]
    if q:
        expenses = [e for e in expenses if _matches(e, q)]
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
        "travelers": list(trip.participants.all()),
        "tab": "expenses",
        "q": q,
        # A search shows only part of a day, so cards can be reordered only in the full list.
        "can_reorder": not q and not trip.is_settled,
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


def _matches(expense: Expense, query: str) -> bool:
    """True when every word of the search appears in the expense's description, payer,
    travelers, type or amount ("12000", "12,000" and "12000 KHR" all find 12,000 KHR)."""
    text = " ".join(
        [
            expense.description,
            expense.payer.name,
            *(b.name for b in expense.beneficiaries.all()),
            str(expense.get_category_display()),
            f"{expense.amount:f}".rstrip("0").rstrip("."),
            format_amount(expense.amount, expense.currency),
            expense.currency,
        ]
    ).casefold()
    return all(word in text for word in query.casefold().split())


@require_POST
def expense_reorder(request: HttpRequest, trip_id) -> HttpResponse:
    """Save the order of one day's cards after a drag: ``ids`` lists the whole day, in order."""
    membership = get_membership(request, trip_id)
    trip = membership.trip
    if trip.is_settled:
        return HttpResponse(status=409)
    ids = request.POST.getlist("ids")
    try:
        day = date.fromisoformat(request.POST.get("day", ""))
        expenses = {str(e.id): e for e in trip.expenses.filter(date=day)}
    except ValueError:
        return HttpResponse(status=400)
    if sorted(ids) != sorted(expenses):
        return HttpResponse(status=409)  # The day changed in the meantime; the page reloads.
    for position, expense_id in enumerate(ids):
        expenses[expense_id].position = position
    Expense.objects.bulk_update(expenses.values(), ["position"])
    return HttpResponse(status=204)


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


def _filter_summary(filters: dict) -> list[str]:
    """The active filters in a few words, for the collapsed filter card: "Person A · Food"."""
    parts = []
    if filters.get("person"):
        parts.append(filters["person"].name)
    if filters.get("category"):
        parts.append(dict(Category.choices).get(filters["category"], filters["category"]))
    start, end = filters.get("start"), filters.get("end")
    if start and end:
        parts.append(f"{date_format(start, 'j M')}–{date_format(end, 'j M')}")
    elif start:
        parts.append(_("from %(day)s") % {"day": date_format(start, "j M")})
    elif end:
        parts.append(_("until %(day)s") % {"day": date_format(end, "j M")})
    return parts


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
    # Day lines carry no total here: the "By day" chart above already shows each day's amount.
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
        filter_summary=_filter_summary(form.filters()) if request.GET else [],
        export_query=query.urlencode(),
        multi_year=len({r.expense.date.year for r in data["rows"]}) > 1,
        people_count=trip.participants.count(),
        travelers=list(trip.participants.all()),
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
