from contextlib import suppress

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.expenses.models import Expense
from apps.settlement.engine import SettlementError

from .access import get_membership
from .forms import ExchangeRateForm, MemberAddForm, ParticipantForm, TripForm
from .models import ExchangeRate, Participant, Trip, TripMember
from .summary import my_balance, named, trip_settlement


def home(request: HttpRequest) -> HttpResponse:
    trips = list(
        Trip.objects.filter(memberships__user=request.user).annotate(
            people_count=Count("participants", distinct=True)
        )
    )
    for trip in trips:
        trip.total = trip.my_balance = None
        with suppress(SettlementError):
            result = trip_settlement(trip)
            trip.total = result.total
            trip.my_balance = my_balance(trip, result, request.user)
    return render(request, "trips/home.html", {"trips": trips})


def trip_create(request: HttpRequest) -> HttpResponse:
    form = TripForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            trip = form.save(commit=False)
            trip.created_by = request.user
            trip.save()
            TripMember.objects.create(trip=trip, user=request.user, role=TripMember.Role.OWNER)
            Participant.objects.create(trip=trip, name=request.user.display_name, user=request.user)
        messages.success(request, _("Trip created. Add the people who travel with you."))
        return redirect("people", trip_id=trip.id)
    return render(request, "trips/trip_form.html", {"form": form})


def trip_settings(request: HttpRequest, trip_id) -> HttpResponse:
    membership = get_membership(request, trip_id, owner_only=True)
    trip = membership.trip
    form = TripForm(request.POST or None, instance=trip)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Trip saved."))
        return redirect("trip_settings", trip_id=trip.id)
    return render(
        request,
        "trips/settings.html",
        {
            "trip": trip,
            "membership": membership,
            "form": form,
            "rate_form": ExchangeRateForm(trip=trip),
            "tab": "settings",
        },
    )


@require_POST
def rate_save(request: HttpRequest, trip_id) -> HttpResponse:
    membership = get_membership(request, trip_id, owner_only=True)
    trip = membership.trip
    existing = trip.rates.filter(currency=request.POST.get("currency")).first()
    form = ExchangeRateForm(request.POST, instance=existing, trip=trip)
    if form.is_valid():
        rate = form.save(commit=False)
        rate.trip = trip
        rate.save()
        messages.success(request, _("Exchange rate saved."))
        return redirect("trip_settings", trip_id=trip.id)
    return render(
        request,
        "trips/settings.html",
        {
            "trip": trip,
            "membership": membership,
            "form": TripForm(instance=trip),
            "rate_form": form,
            "tab": "settings",
        },
    )


def rate_delete(request: HttpRequest, trip_id, rate_id) -> HttpResponse:
    membership = get_membership(request, trip_id, owner_only=True)
    rate = get_object_or_404(ExchangeRate, pk=rate_id, trip=membership.trip)
    in_use = membership.trip.expenses.filter(currency=rate.currency).exists()
    if request.method == "POST" and not in_use:
        rate.delete()
        messages.success(request, _("Exchange rate deleted."))
        return redirect("trip_settings", trip_id=trip_id)
    return render(
        request,
        "trips/confirm_delete.html",
        {
            "trip": membership.trip,
            "membership": membership,
            "object": f"{rate.currency} {rate.rate}",
            "blocked": _("Expenses use this currency. Change them first.") if in_use else "",
            "button": _("Delete rate"),
            "back": reverse("trip_settings", args=[trip_id]),
        },
    )


def trip_delete(request: HttpRequest, trip_id) -> HttpResponse:
    membership = get_membership(request, trip_id, owner_only=True)
    if request.method == "POST":
        name = membership.trip.name
        membership.trip.delete()
        messages.success(request, _("Trip “%(name)s” deleted.") % {"name": name})
        return redirect("home")
    return render(
        request,
        "trips/confirm_delete.html",
        {
            "trip": membership.trip,
            "membership": membership,
            "object": membership.trip.name,
            "warning": _("All expenses of this trip are deleted too. This cannot be undone."),
            "button": _("Delete trip"),
            "back": reverse("trip_settings", args=[trip_id]),
        },
    )


def people(request: HttpRequest, trip_id) -> HttpResponse:
    membership = get_membership(request, trip_id)
    trip = membership.trip
    member_form = MemberAddForm(trip=trip, prefix="m")
    if request.method == "POST":
        if not membership.is_owner:
            return HttpResponse(status=403)
        if "add_member" in request.POST:
            member_form = MemberAddForm(request.POST, trip=trip, prefix="m")
            if member_form.is_valid():
                TripMember.objects.create(trip=trip, user=member_form.user)
                messages.success(
                    request,
                    _("%(name)s can now open this trip.") % {"name": member_form.user.display_name},
                )
                return redirect("people", trip_id=trip.id)
    return render(
        request,
        "trips/people.html",
        {
            "trip": trip,
            "membership": membership,
            "participants": trip.participants.select_related("user").prefetch_related("sponsors"),
            "members": trip.memberships.select_related("user").order_by("-role", "created_at"),
            "member_form": member_form,
            "tab": "people",
        },
    )


def participant_create(request: HttpRequest, trip_id) -> HttpResponse:
    membership = get_membership(request, trip_id, owner_only=True)
    trip = membership.trip
    form = ParticipantForm(request.POST or None, trip=trip)
    if request.method == "POST" and form.is_valid():
        participant = form.save(commit=False)
        participant.trip = trip
        participant.save()
        form.save_m2m()
        messages.success(request, _("%(name)s added.") % {"name": participant.name})
        if "add_another" in request.POST:
            return redirect("participant_create", trip_id=trip.id)
        return redirect("people", trip_id=trip.id)
    return render(
        request,
        "trips/participant_form.html",
        {"trip": trip, "membership": membership, "form": form},
    )


def participant_edit(request: HttpRequest, trip_id, participant_id) -> HttpResponse:
    membership = get_membership(request, trip_id, owner_only=True)
    participant = get_object_or_404(Participant, pk=participant_id, trip=membership.trip)
    form = ParticipantForm(request.POST or None, instance=participant, trip=membership.trip)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("%(name)s saved.") % {"name": participant.name})
        return redirect("people", trip_id=trip_id)
    return render(
        request,
        "trips/participant_form.html",
        {
            "trip": membership.trip,
            "membership": membership,
            "form": form,
            "participant": participant,
            "tab": "people",
        },
    )


def participant_delete(request: HttpRequest, trip_id, participant_id) -> HttpResponse:
    membership = get_membership(request, trip_id, owner_only=True)
    participant = get_object_or_404(Participant, pk=participant_id, trip=membership.trip)
    in_use = membership.trip.expenses.filter(
        Q(payer=participant) | Q(beneficiaries=participant)
    ).exists()
    if request.method == "POST" and not in_use:
        with transaction.atomic():
            # Deleted expenses are kept for the record but must not block removing a person.
            Expense.all_objects.filter(payer=participant).delete()
            participant.delete()
        messages.success(request, _("%(name)s removed.") % {"name": participant.name})
        return redirect("people", trip_id=trip_id)
    return render(
        request,
        "trips/confirm_delete.html",
        {
            "trip": membership.trip,
            "membership": membership,
            "object": participant.name,
            "blocked": _("This person appears in expenses. Change those expenses first.")
            if in_use
            else "",
            "button": _("Remove person"),
            "back": reverse("participant_edit", args=[trip_id, participant.id]),
        },
    )


@require_POST
def member_remove(request: HttpRequest, trip_id, member_id) -> HttpResponse:
    membership = get_membership(request, trip_id, owner_only=True)
    member = get_object_or_404(TripMember, pk=member_id, trip=membership.trip)
    if member.is_owner:
        messages.error(request, _("The owner cannot be removed."))
    else:
        member.delete()
        messages.success(
            request,
            _("%(name)s can no longer open this trip.") % {"name": member.user.display_name},
        )
    return redirect("people", trip_id=trip_id)


def summary(request: HttpRequest, trip_id) -> HttpResponse:
    membership = get_membership(request, trip_id)
    trip = membership.trip
    context = {"trip": trip, "membership": membership, "tab": "summary"}
    try:
        context["summary"] = named(trip, trip_settlement(trip), request.user)
    except SettlementError as error:
        context["error"] = str(error)
    return render(request, "trips/summary.html", context)
