"""The dispute section of the expense page (spec section 5.4) and the notifications list (section 4).

There is no dispute page: every action posts here and returns to the expense page.
"""

from urllib.parse import quote

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.expenses.models import Expense
from apps.trips.access import get_membership
from apps.trips.pagination import paginate

from . import rules
from .models import Dispute, DisputeMessage, Notification

DRAFT_KEY = "dispute_draft"


def _keep_draft(request: HttpRequest, form: str, target, text_field: str, english_field: str):
    """The English copy could not be made: keep what was typed, so the expense page shows the
    same form again with the English box open and the text still in it."""
    request.session[DRAFT_KEY] = {
        "form": form,
        "target": str(target),
        "text": request.POST.get(text_field, ""),
        "english": request.POST.get(english_field, ""),
    }


def section(membership, expense: Expense | None, request: HttpRequest | None = None) -> dict:
    """What the dispute section of an expense page needs: the disputes with what this account
    may do in each, and whether it may open a new one. ``expense`` is None when it was erased."""
    if expense is None:
        return {"disputes": [], "can_dispute": False}
    trip = membership.trip
    disputes = list(
        expense.disputes.select_related("expense__payer").prefetch_related(
            Prefetch("messages", queryset=DisputeMessage.objects.order_by("created_at", "id"))
        )
    )
    for d in disputes:
        d.can_write = d.is_open and not trip.is_settled and rules.may_write(membership, d)
        d.can_resolve = d.is_open and not trip.is_settled and rules.may_resolve(membership, d)
        d.can_close = d.is_open and not trip.is_settled and rules.may_close(membership)
    can_dispute = (
        not trip.is_settled
        and rules.may_open(membership, expense)
        and not any(d.is_open and d.opened_by_id == membership.user_id for d in disputes)
    )
    draft = request.session.pop(DRAFT_KEY, None) if request is not None else None
    new_draft = None
    if draft:
        if draft["form"] == "open":
            new_draft = draft
        for d in disputes:
            d.draft = draft if draft["form"] != "open" and draft["target"] == str(d.pk) else None
    return {
        "disputes": disputes,
        "can_dispute": can_dispute,
        "dispute_expense_id": expense.pk,
        "new_draft": new_draft,
    }


def open_ids(trip) -> set:
    """The expenses of the trip with an open dispute, for the "Disputed" mark and the filter."""
    return set(
        Dispute.objects.filter(trip=trip, state=Dispute.State.OPEN).values_list(
            "expense_id", flat=True
        )
    )


def _back(request: HttpRequest, trip_id, expense_id):
    """Back to the expense page, keeping where it was opened from."""
    url = reverse("expense_edit", args=[trip_id, expense_id])
    target = request.POST.get("next", "")
    if target.startswith(f"/trips/{trip_id}/") and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}
    ):
        url += "?next=" + quote(target)
    return redirect(url + "#disputes")


def _dispute(membership, dispute_id) -> Dispute:
    return get_object_or_404(
        Dispute.objects.select_related("expense__payer", "trip"),
        pk=dispute_id,
        trip=membership.trip,
    )


@require_POST
def dispute_open(request: HttpRequest, trip_id, expense_id) -> HttpResponse:
    membership = get_membership(request, trip_id)
    expense = get_object_or_404(
        Expense.all_objects.select_related("payer"), pk=expense_id, trip=membership.trip
    )
    if not rules.may_open(membership, expense):
        raise PermissionDenied
    try:
        rules.open_dispute(
            membership, expense, request.POST.get("reason", ""), request.POST.get("reason_en", "")
        )
    except rules.DisputeRefused as refused:
        if isinstance(refused, rules.EnglishNeeded):
            _keep_draft(request, "open", expense_id, "reason", "reason_en")
        messages.error(request, str(refused))
    else:
        messages.success(request, _("Dispute opened."))
    return _back(request, trip_id, expense_id)


@require_POST
def dispute_write(request: HttpRequest, trip_id, dispute_id) -> HttpResponse:
    membership = get_membership(request, trip_id)
    dispute = _dispute(membership, dispute_id)
    if not rules.may_write(membership, dispute):
        raise PermissionDenied
    try:
        rules.write_message(
            membership, dispute, request.POST.get("text", ""), request.POST.get("text_en", "")
        )
    except rules.DisputeRefused as refused:
        if isinstance(refused, rules.EnglishNeeded):
            _keep_draft(request, "write", dispute_id, "text", "text_en")
        messages.error(request, str(refused))
    return _back(request, trip_id, dispute.expense_id)


@require_POST
def dispute_resolve(request: HttpRequest, trip_id, dispute_id) -> HttpResponse:
    membership = get_membership(request, trip_id)
    dispute = _dispute(membership, dispute_id)
    if not rules.may_resolve(membership, dispute):
        raise PermissionDenied
    try:
        rules.resolve(membership, dispute)
    except rules.DisputeRefused as refused:
        messages.error(request, str(refused))
    else:
        messages.success(request, _("Dispute resolved."))
    return _back(request, trip_id, dispute.expense_id)


@require_POST
def dispute_close(request: HttpRequest, trip_id, dispute_id) -> HttpResponse:
    membership = get_membership(request, trip_id, owner_only=True)
    dispute = _dispute(membership, dispute_id)
    try:
        rules.close(
            membership, dispute, request.POST.get("reason", ""), request.POST.get("reason_en", "")
        )
    except rules.DisputeRefused as refused:
        if isinstance(refused, rules.EnglishNeeded):
            _keep_draft(request, "close", dispute_id, "reason", "reason_en")
        messages.error(request, str(refused))
    else:
        messages.success(request, _("Dispute closed."))
    return _back(request, trip_id, dispute.expense_id)


def notification_list(request: HttpRequest) -> HttpResponse:
    """The account's notifications, newest first. Opening the list marks them as read; the
    items that were unread keep their mark on this one view."""
    items = Notification.objects.visible_to(request.user).select_related("trip")
    page = paginate(request, items)
    shown = list(page.object_list)
    for item in shown:
        item.text = rules.notification_text(item)
    Notification.objects.filter(user=request.user, read_at__isnull=True).update(
        read_at=timezone.now()
    )
    return render(request, "notifications.html", {"page": page, "items": shown})
