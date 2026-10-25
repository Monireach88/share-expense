from contextlib import suppress
from datetime import timedelta
from itertools import groupby

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.settlement.engine import SettlementError, to_base
from apps.trips.access import get_membership
from apps.trips.summary import my_balance, trip_settlement
from apps.trips.templatetags.ui import format_amount

from .forms import ExpenseForm
from .models import Expense

MAX_DAY_CHIPS = 14


def expense_list(request: HttpRequest, trip_id) -> HttpResponse:
    membership = get_membership(request, trip_id)
    trip = membership.trip
    expenses = list(trip.expenses.select_related("payer").prefetch_related("beneficiaries"))
    rates = trip.rate_map()
    for e in expenses:
        e.base_amount = None
        with suppress(SettlementError):
            e.base_amount = to_base(e.amount, e.currency, trip.base_currency, rates)
    days = []
    for day, items in groupby(expenses, key=lambda e: e.date):
        items = list(items)
        amounts = [e.base_amount for e in items]
        days.append((day, items, None if None in amounts else sum(amounts)))
    context = {
        "trip": trip,
        "membership": membership,
        "days": days,
        "multi_year": len({day.year for day, _items, _sum in days}) > 1,
        "people_count": trip.participants.count(),
        "tab": "expenses",
    }
    try:
        result = trip_settlement(trip)
        context["total"] = result.total
        context["my_balance"] = my_balance(trip, result, request.user)
    except SettlementError as error:
        context["error"] = str(error)
    return render(request, "expenses/list.html", context)


def _initial(request: HttpRequest, trip) -> dict:
    """Sensible defaults: today, the current user as payer, everyone as beneficiary, last currency."""
    last = trip.expenses.filter(created_by=request.user).order_by("-created_at").first()
    me = trip.participants.filter(user=request.user).first()
    today = timezone.localdate()
    in_trip = (not trip.start_date or trip.start_date <= today) and (
        not trip.end_date or today <= trip.end_date
    )
    return {
        "date": today if in_trip or not trip.start_date else trip.start_date,
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
