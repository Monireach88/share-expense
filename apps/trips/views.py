from contextlib import suppress

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.disputes import rules as dispute_rules
from apps.disputes.models import Dispute
from apps.expenses.models import Expense
from apps.settlement.engine import SettlementError

from . import actions, history, invites
from .access import get_membership, locked
from .forms import ExchangeRateForm, InviteForm, MemberRoleForm, ParticipantForm, TripForm
from .models import ExchangeRate, Invite, Participant, Trip, TripMember
from .offline import cacheable_page
from .pagination import paginate
from .summary import named, trip_settlement, trip_status


@cacheable_page
def home(request: HttpRequest) -> HttpResponse:
    trips = Trip.objects.filter(memberships__user=request.user).annotate(
        people_count=Count("participants", distinct=True)
    )
    page = paginate(request, trips)
    for trip in page.object_list:
        trip.total = result = None
        with suppress(SettlementError):
            result = trip_settlement(trip)
            trip.total = result.total
        trip.status = trip_status(trip, result)
    return render(request, "trips/home.html", {"trips": page.object_list, "page": page})


def trip_create(request: HttpRequest) -> HttpResponse:
    form = TripForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            trip = form.save(commit=False)
            trip.created_by = request.user
            trip.save()
            TripMember.objects.create(trip=trip, user=request.user, role=TripMember.Role.OWNER)
            Participant.objects.create(trip=trip, name=request.user.display_name, user=request.user)
        messages.success(request, _("Trip created."))
        return redirect("people", trip_id=trip.id)
    return render(request, "trips/trip_form.html", {"form": form})


def trip_settings(request: HttpRequest, trip_id) -> HttpResponse:
    membership = get_membership(request, trip_id, owner_only=True)
    trip = membership.trip
    form = TripForm(request.POST or None, instance=trip)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            _record_trip_changes(trip, membership, form)
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


def _record_trip_changes(trip: Trip, membership: TripMember, form: TripForm) -> None:
    """History: a new name is "renamed"; the other settings go into one "changed" entry."""
    if "name" in form.changed_data:
        history.record(
            trip,
            membership,
            "renamed",
            "trip",
            object_id=trip.pk,
            label=trip.name,
            changes={"name": history.change(form.initial["name"], trip.name)},
        )
    others = {}
    for field in ("country", "start_date", "end_date", "base_currency"):
        if field in form.changed_data:
            old, new = form.initial.get(field), form.cleaned_data.get(field)
            others[field] = history.change(
                history.setting_text(field, old),
                history.setting_text(field, new),
                label=str(form[field].label).lower(),
            )
    if others:
        history.record(
            trip, membership, "changed", "trip", object_id=trip.pk, label=trip.name, changes=others
        )


@require_POST
def rate_save(request: HttpRequest, trip_id) -> HttpResponse:
    membership = get_membership(request, trip_id, owner_only=True)
    if response := locked(request, membership.trip):
        return response
    trip = membership.trip
    existing = trip.rates.filter(currency=request.POST.get("currency")).first()
    # The form edits ``existing`` in place, so its old rate is read first.
    old = history.rate_line(trip, existing.currency, existing.rate) if existing else ""
    form = ExchangeRateForm(request.POST, instance=existing, trip=trip)
    if form.is_valid():
        rate = form.save(commit=False)
        rate.trip = trip
        with transaction.atomic():
            rate.save()
            new = history.rate_line(trip, rate.currency, rate.rate)
            if existing is None:
                action = "added"
            elif old != new:
                action = "changed"
            else:
                action = None
            if action:
                history.record(
                    trip,
                    membership,
                    action,
                    "rate",
                    object_id=rate.pk,
                    label=rate.currency,
                    changes={"rate": history.change(old, new)},
                )
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
    if response := locked(request, membership.trip):
        return response
    rate = get_object_or_404(ExchangeRate, pk=rate_id, trip=membership.trip)
    in_use = membership.trip.expenses.filter(currency=rate.currency).exists()
    disputed = Dispute.objects.filter(
        trip=membership.trip, expense__currency=rate.currency
    ).exists()
    if request.method == "POST" and not in_use and not disputed:
        with transaction.atomic():
            history.record(
                membership.trip,
                membership,
                "removed",
                "rate",
                object_id=rate.pk,
                label=rate.currency,
                changes={
                    "rate": history.change(
                        history.rate_line(membership.trip, rate.currency, rate.rate), ""
                    )
                },
            )
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
            "blocked": _("Expenses use this currency. Change them first.")
            if in_use
            else dispute_rules.disputes_in_use_message("rate")
            if disputed
            else "",
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


@cacheable_page
def people(request: HttpRequest, trip_id) -> HttpResponse:
    membership = get_membership(request, trip_id)
    trip = membership.trip
    pending, new_link = [], None
    if membership.is_owner:
        pending = list(invites.open_invites(trip))
        for invite in pending:
            invite.expired = invites.is_expired(invite)
            invite.expires_text = invites.expiry_text(invite)
        new_link = request.session.pop(NEW_LINK_KEY, None)
        if new_link and not any(i.pk == new_link["id"] for i in pending):
            new_link = None
    response = render(
        request,
        "trips/people.html",
        {
            "trip": trip,
            "membership": membership,
            "participants": paginate(
                request, trip.participants.select_related("user").prefetch_related("sponsors")
            ),
            "members": _members(trip),
            "pending": pending,
            "new_link": new_link,
            "tab": "people",
        },
    )
    if pending or new_link:
        response.no_sw_cache = True  # Addresses and the secret link are not kept by the browser.
    return response


ROLE_ORDER = [TripMember.Role.OWNER, TripMember.Role.EDITOR, TripMember.Role.MEMBER]


def _members(trip) -> list[TripMember]:
    """The trip's accounts, Owner first, then Editors, then Members; each with its traveler."""
    linked = {p.user_id: p for p in trip.participants.filter(user__isnull=False)}
    members = sorted(
        trip.memberships.select_related("user").order_by("created_at"),
        key=lambda m: ROLE_ORDER.index(m.role),
    )
    for m in members:
        m.trip = trip
        m.linked_traveler = linked.get(m.user_id)  # Fills the cached property: no extra query.
    return members


def participant_create(request: HttpRequest, trip_id) -> HttpResponse:
    membership = get_membership(request, trip_id, owner_only=True)
    if response := locked(request, membership.trip):
        return response
    trip = membership.trip
    form = ParticipantForm(request.POST or None, trip=trip)
    if request.method == "POST" and form.is_valid():
        participant = form.save(commit=False)
        participant.trip = trip
        with transaction.atomic():
            participant.save()
            form.save_m2m()
            history.record_traveler_changes(trip, membership, participant, None)
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
    """On a settled trip only the linked account can change; ParticipantForm locks the rest."""
    membership = get_membership(request, trip_id, owner_only=True)
    participant = get_object_or_404(Participant, pk=participant_id, trip=membership.trip)
    before = history.traveler_state(participant) if request.method == "POST" else None
    form = ParticipantForm(request.POST or None, instance=participant, trip=membership.trip)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            history.record_traveler_changes(membership.trip, membership, participant, before)
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
    if response := locked(request, membership.trip):
        return response
    participant = get_object_or_404(Participant, pk=participant_id, trip=membership.trip)
    in_use = membership.trip.expenses.filter(
        Q(payer=participant) | Q(beneficiaries=participant)
    ).exists()
    # Removing the traveler erases the deleted expenses they paid, so a dispute on any expense
    # with them, deleted or not, blocks it (spec section 3).
    disputed = Dispute.objects.filter(
        Q(expense__payer=participant) | Q(expense__beneficiaries=participant),
        trip=membership.trip,
    ).exists()
    if request.method == "POST" and not in_use and not disputed:
        with transaction.atomic():
            # Deleted expenses are kept for the record but must not block removing a person.
            Expense.all_objects.filter(payer=participant).delete()
            history.record(
                membership.trip,
                membership,
                "removed",
                "traveler",
                object_id=participant.pk,
                label=participant.name,
            )
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
            "blocked": _("This traveler appears in expenses. Change those expenses first.")
            if in_use
            else dispute_rules.disputes_in_use_message("traveler")
            if disputed
            else "",
            "button": _("Remove traveler"),
            "back": reverse("participant_edit", args=[trip_id, participant.id]),
        },
    )


# --- Inviting a person (spec section 6.2) --------------------------------------------------------

NEW_LINK_KEY = "new_invite_link"


def _show_link(request: HttpRequest, invite: Invite, token: str) -> None:
    """Keep the new link for the next Travelers page only: it is the one place it is shown."""
    request.session[NEW_LINK_KEY] = {
        "id": invite.pk,
        "url": invites.link_for(request, token),
        "email": invite.email,
        "expires": invites.expiry_text(invite),
    }


def _email_message(request: HttpRequest, outcome: invites.Outcome) -> None:
    (messages.success if outcome.sent else messages.error)(request, outcome.message)


def invite_new(request: HttpRequest, trip_id) -> HttpResponse:
    """One form for both cases, then a confirmation: an approved account joins at once, any
    other email address gets a personal invite (its link is shown on the Travelers page)."""
    membership = get_membership(request, trip_id, owner_only=True)
    trip = membership.trip
    data = request.POST or None
    if data is not None and data.get("use_suggestion"):
        # "Use dan@gmail.com" on the confirmation: ask again with the corrected address.
        data = data.copy()
        data["who"] = data["use_suggestion"]
        data.pop("confirm", None)
    form = InviteForm(data, trip=trip)
    question = None
    if request.method == "POST" and "back" not in request.POST and form.is_valid():
        if "confirm" not in data:
            question = _question(form)
        elif form.user is not None:
            try:
                actions.add_member(
                    trip,
                    form.user,
                    by=membership,
                    traveler=form.participant,
                    new_traveler_name=form.new_traveler_name,
                )
            except actions.ActionRefused as refused:
                form.add_error(None, str(refused))
            else:
                messages.success(
                    request,
                    _("%(name)s can now open this trip.") % {"name": form.user.display_name},
                )
                return redirect("people", trip_id=trip.id)
        else:
            invite, token = invites.create(
                trip,
                form.email,
                by=membership,
                traveler=form.participant,
                new_traveler_name=form.new_traveler_name,
            )
            _show_link(request, invite, token)
            _email_message(
                request, invites.send_email(invite, invites.link_for(request, token), request.user)
            )
            return redirect("people", trip_id=trip.id)
    return render(
        request,
        "trips/invite_form.html",
        {"trip": trip, "membership": membership, "form": form, "question": question},
    )


def _question(form: InviteForm) -> dict:
    """The confirmation card: a title naming exactly who, and a second line with the traveler."""
    if form.user is not None:
        title = _("Add %(name)s (%(username)s) to this trip now?") % {
            "name": form.user.display_name,
            "username": form.user.username,
        }
    else:
        title = _("Invite %(email)s?") % {"email": form.email}
    if form.participant is not None:
        detail = _("As %(name)s") % {"name": form.participant.name}
    elif form.new_traveler_name:
        detail = _("As new traveler %(name)s") % {"name": form.new_traveler_name}
    else:
        detail = _("As Viewer")
    return {"title": title, "detail": detail, "suggestion": form.suggestion}


def _open_invite(membership: TripMember, invite_id) -> Invite:
    return get_object_or_404(
        Invite.objects.select_related("trip"),
        pk=invite_id,
        trip=membership.trip,
        state__in=Invite.OPEN_STATES,
    )


@require_POST
def invite_copy(request: HttpRequest, trip_id, invite_id) -> HttpResponse:
    """A new link to copy: the old link stops working and the 7 days start again."""
    membership = get_membership(request, trip_id, owner_only=True)
    invite = _open_invite(membership, invite_id)
    token = invites.renew(invite, by=membership, again=False)
    invite.refresh_from_db()
    _show_link(request, invite, token)
    return redirect("people", trip_id=trip_id)


@require_POST
def invite_resend(request: HttpRequest, trip_id, invite_id) -> HttpResponse:
    """A new link by email, also for an expired invite; the old link stops working."""
    membership = get_membership(request, trip_id, owner_only=True)
    invite = _open_invite(membership, invite_id)
    token = invites.renew(invite, by=membership, again=True)
    invite.refresh_from_db()
    _show_link(request, invite, token)
    _email_message(
        request, invites.send_email(invite, invites.link_for(request, token), request.user)
    )
    return redirect("people", trip_id=trip_id)


@require_POST
def invite_cancel(request: HttpRequest, trip_id, invite_id) -> HttpResponse:
    membership = get_membership(request, trip_id, owner_only=True)
    invite = _open_invite(membership, invite_id)
    invites.cancel(invite, by=membership)
    messages.success(request, _("The invite for %(email)s is cancelled.") % {"email": invite.email})
    return redirect("people", trip_id=trip_id)


@require_POST
def trip_leave(request: HttpRequest, trip_id) -> HttpResponse:
    """A Member or an Editor leaves the trip (spec section 6.4); the Owner cannot."""
    membership = get_membership(request, trip_id)
    try:
        actions.leave_trip(membership)
    except actions.ActionRefused as refused:
        messages.error(request, str(refused))
        return redirect("people", trip_id=trip_id)
    messages.success(request, _("You left %(trip)s.") % {"trip": membership.trip.name})
    return redirect("home")


@require_POST
def member_remove(request: HttpRequest, trip_id, member_id) -> HttpResponse:
    membership = get_membership(request, trip_id, owner_only=True)
    member = get_object_or_404(
        TripMember.objects.select_related("user", "trip"), pk=member_id, trip=membership.trip
    )
    try:
        actions.remove_member(member, by=membership)
    except actions.ActionRefused as refused:
        messages.error(request, str(refused))
    else:
        messages.success(
            request,
            _("%(name)s can no longer open this trip.") % {"name": member.user.display_name},
        )
    return redirect("people", trip_id=trip_id)


def _other_member(membership: TripMember, member_id) -> TripMember:
    """Another account on the Owner's trip. The Owner's own row has no page: 404."""
    return get_object_or_404(
        TripMember.objects.select_related("user", "trip").exclude(pk=membership.pk),
        pk=member_id,
        trip=membership.trip,
    )


def member_edit(request: HttpRequest, trip_id, member_id) -> HttpResponse:
    """One account on the trip: its role, make it the owner, or remove it. Owner only."""
    membership = get_membership(request, trip_id, owner_only=True)
    member = _other_member(membership, member_id)
    form = MemberRoleForm(
        request.POST or None, initial={"role": member.role}, traveler=member.linked_traveler
    )
    if request.method == "POST" and form.is_valid():
        try:
            actions.change_role(member, form.cleaned_data["role"], by=membership)
        except actions.ActionRefused as refused:
            messages.error(request, str(refused))
        else:
            if member.is_editor:
                text = _("%(name)s is now an Editor.")
            else:
                text = _("%(name)s is now a Member.")
            messages.success(request, text % {"name": member.user.display_name})
        return redirect("people", trip_id=trip_id)
    return render(
        request,
        "trips/member_edit.html",
        {
            "trip": membership.trip,
            "membership": membership,
            "member": member,
            "form": form,
            "remove_question": _remove_question(member),
        },
    )


def _remove_question(member: TripMember) -> str:
    name = member.user.display_name
    if traveler := member.linked_traveler:
        return _(
            "Remove %(name)s from this trip? %(name)s loses access at once and is no longer "
            "linked to %(traveler)s."
        ) % {"name": name, "traveler": traveler.name}
    return _("Remove %(name)s from this trip? %(name)s loses access at once.") % {"name": name}


def member_transfer(request: HttpRequest, trip_id, member_id) -> HttpResponse:
    """Make another approved account the Owner, after a confirmation; the old Owner becomes an Editor."""
    membership = get_membership(request, trip_id, owner_only=True)
    member = _other_member(membership, member_id)
    blocked = (
        _("This account is closed.")
        if member.user.is_closed
        else ""
        if member.user.is_active
        else _("This account is not approved yet.")
    )
    if request.method == "POST" and not blocked:
        try:
            actions.transfer_ownership(member, by=membership)
        except actions.ActionRefused as refused:
            messages.error(request, str(refused))
        else:
            messages.success(
                request, _("%(name)s is now the Owner.") % {"name": member.user.display_name}
            )
        return redirect("people", trip_id=trip_id)
    return render(
        request,
        "trips/confirm_delete.html",
        {
            "trip": membership.trip,
            "membership": membership,
            "object": member.user.display_name,
            "title": _("Make %(name)s the Owner?") % {"name": member.user.display_name},
            "warning": _(
                "%(name)s will have full control of this trip. You will become an Editor and "
                "cannot undo this yourself; only %(name)s can make you the Owner again."
            )
            % {"name": member.user.display_name},
            "blocked": blocked,
            "button": _("Make %(name)s the Owner") % {"name": member.user.display_name},
            "button_class": "btn",
            "back": reverse("member_edit", args=[trip_id, member.id]),
        },
    )


@cacheable_page
def summary(request: HttpRequest, trip_id) -> HttpResponse:
    membership = get_membership(request, trip_id)
    trip = membership.trip
    context = {
        "trip": trip,
        "membership": membership,
        "tab": "summary",
        "open_disputes": Dispute.objects.filter(trip=trip, state=Dispute.State.OPEN).count(),
    }
    try:
        context["summary"] = named(trip, trip_settlement(trip), request.user)
    except SettlementError as error:
        context["error"] = str(error)
    return render(request, "trips/summary.html", context)


@require_POST
def trip_settle(request: HttpRequest, trip_id) -> HttpResponse:
    membership = get_membership(request, trip_id, managers_only=True)
    try:
        actions.settle(membership.trip, by=membership)
    except actions.ActionRefused as refused:
        return HttpResponse(str(refused), status=400, content_type="text/plain; charset=utf-8")
    return redirect("summary", trip_id=trip_id)


@require_POST
def trip_reopen(request: HttpRequest, trip_id) -> HttpResponse:
    membership = get_membership(request, trip_id, managers_only=True)
    actions.reopen(membership.trip, by=membership)
    return redirect("summary", trip_id=trip_id)
