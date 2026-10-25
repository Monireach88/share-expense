from contextlib import suppress
from itertools import groupby

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.settlement.engine import SettlementError, to_base
from apps.trips.access import get_membership

from .forms import ExpenseForm
from .models import Expense


def expense_list(request: HttpRequest, trip_id) -> HttpResponse:
    membership = get_membership(request, trip_id)
    trip = membership.trip
    expenses = list(trip.expenses.select_related("payer").prefetch_related("beneficiaries"))
    people_count = trip.participants.count()
    rates = trip.rate_map()
    total = None
    with suppress(SettlementError):
        total = sum((to_base(e.amount, e.currency, trip.base_currency, rates) for e in expenses), 0)
    days = [(day, list(items)) for day, items in groupby(expenses, key=lambda e: e.date)]
    return render(
        request,
        "expenses/list.html",
        {
            "trip": trip,
            "membership": membership,
            "days": days,
            "people_count": people_count,
            "total": total,
            "tab": "expenses",
        },
    )


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
        messages.success(request, _("Expense added."))
        if "add_another" in request.POST:
            return redirect("expense_create", trip_id=trip.id)
        return redirect("trip", trip_id=trip.id)
    return render(
        request,
        "expenses/form.html",
        {"trip": trip, "membership": membership, "form": form, "tab": "expenses"},
    )


def expense_edit(request: HttpRequest, trip_id, expense_id) -> HttpResponse:
    membership = get_membership(request, trip_id)
    expense = get_object_or_404(Expense, pk=expense_id, trip=membership.trip)
    form = ExpenseForm(request.POST or None, instance=expense, trip=membership.trip)
    if request.method == "POST" and form.is_valid():
        expense = form.save(commit=False)
        expense.updated_by = request.user
        expense.save()
        form.save_m2m()
        messages.success(request, _("Expense saved."))
        return redirect("trip", trip_id=trip_id)
    return render(
        request,
        "expenses/form.html",
        {
            "trip": membership.trip,
            "membership": membership,
            "form": form,
            "expense": expense,
            "tab": "expenses",
        },
    )


def expense_delete(request: HttpRequest, trip_id, expense_id) -> HttpResponse:
    membership = get_membership(request, trip_id)
    expense = get_object_or_404(Expense, pk=expense_id, trip=membership.trip)
    if request.method == "POST":
        expense.deleted_at = timezone.now()
        expense.updated_by = request.user
        expense.save(update_fields=["deleted_at", "updated_by", "updated_at"])
        messages.success(request, _("Expense deleted."))
        return redirect("trip", trip_id=trip_id)
    return render(
        request,
        "trips/confirm_delete.html",
        {
            "trip": membership.trip,
            "membership": membership,
            "object": f"{expense} — {expense.amount} {expense.currency}",
            "button": _("Delete expense"),
            "back": "trip",
        },
    )
