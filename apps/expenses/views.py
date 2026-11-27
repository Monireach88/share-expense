from contextlib import suppress
from datetime import date, timedelta
from decimal import Decimal
from itertools import groupby
from urllib.parse import quote

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Max
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.http import require_POST

from apps.settlement.engine import SettlementError, to_base
from apps.trips import history
from apps.trips.access import get_membership, lock_trip, locked
from apps.trips.offline import cacheable_page
from apps.trips.pagination import DayPage
from apps.trips.summary import named, trip_settlement
from apps.trips.templatetags.ui import format_amount

from . import ai_fill, suggest
from .forms import CategoryForm, ExpenseForm
from .models import DEFAULT_EMOJI, EMOJI_CHOICES, Category, Expense
from .report import ReportFilterForm, build_report, export_rows, to_csv, to_xlsx

MAX_DAY_CHIPS = 14


@cacheable_page
def expense_list(request: HttpRequest, trip_id) -> HttpResponse:
    membership = get_membership(request, trip_id)
    trip = membership.trip
    expenses = list(
        trip.expenses.select_related("payer", "category").prefetch_related("beneficiaries")
    )
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
        "ai_enabled": suggest.enabled(),
        "q": q,
        # A search shows only part of a day, so cards can be reordered only in the full list.
        "can_reorder": membership.can_manage_expenses and not q and not trip.is_settled,
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
            expense.category.name if expense.category else "",
            f"{expense.amount:f}".rstrip("0").rstrip("."),
            format_amount(expense.amount, expense.currency),
            expense.currency,
        ]
    ).casefold()
    return all(word in text for word in query.casefold().split())


@require_POST
def expense_reorder(request: HttpRequest, trip_id) -> HttpResponse:
    """Save the order of one day's cards after a drag: ``ids`` lists the whole day, in order."""
    membership = get_membership(request, trip_id, managers_only=True)
    ids = request.POST.getlist("ids")
    try:
        day = date.fromisoformat(request.POST.get("day", ""))
    except ValueError:
        return HttpResponse(status=400)
    with transaction.atomic():
        trip = lock_trip(membership.trip)
        if trip.is_settled:
            return HttpResponse(status=409)
        expenses = {str(e.id): e for e in trip.expenses.filter(date=day)}
        if sorted(ids) != sorted(expenses):
            return HttpResponse(status=409)  # The day changed in the meantime; the page reloads.
        for position, expense_id in enumerate(ids):
            expenses[expense_id].position = position
        Expense.objects.bulk_update(expenses.values(), ["position"])
    return HttpResponse(status=204)


def _category_json(category: Category, status: int = 200) -> JsonResponse:
    return JsonResponse(
        {"id": category.pk, "name": category.name, "emoji": category.emoji}, status=status
    )


def _form_error(form) -> JsonResponse:
    errors = [e for field in form.errors.values() for e in field]
    return JsonResponse({"error": errors[0] if errors else _("Check the name.")}, status=400)


@require_POST
def category_create(request: HttpRequest, trip_id) -> HttpResponse:
    """Add a type from the expense form; answers JSON so the form keeps what was typed.
    Everyone who may add an expense may add a type; only Owner and Editors rename or remove."""
    membership = get_membership(request, trip_id, can_add=True)
    trip = membership.trip
    form = CategoryForm(request.POST, trip=trip)
    if not form.is_valid():
        return _form_error(form)
    with transaction.atomic():
        if lock_trip(trip).is_settled:
            return JsonResponse({"error": _("This trip is settled.")}, status=409)
        category = form.save(commit=False)
        category.trip = trip
        category.position = (trip.categories.aggregate(m=Max("position"))["m"] or 0) + 1
        category.save()
        history.record(
            trip, membership, "added", "type", object_id=category.pk, label=category.name
        )
    return _category_json(category, status=201)


@require_POST
def category_edit(request: HttpRequest, trip_id, category_id) -> HttpResponse:
    membership = get_membership(request, trip_id, managers_only=True)
    trip = membership.trip
    category = get_object_or_404(Category, pk=category_id, trip=trip)
    old_name, old_emoji = category.name, category.emoji
    form = CategoryForm(request.POST, instance=category, trip=trip)
    if not form.is_valid():
        return _form_error(form)
    with transaction.atomic():
        if lock_trip(trip).is_settled:
            return JsonResponse({"error": _("This trip is settled.")}, status=409)
        category = form.save()
        if category.name != old_name:
            history.record(
                trip,
                membership,
                "renamed",
                "type",
                object_id=category.pk,
                label=category.name,
                changes={"name": history.change(old_name, category.name)},
            )
        if category.emoji != old_emoji:
            history.record(
                trip,
                membership,
                "changed",
                "type",
                object_id=category.pk,
                label=category.name,
                changes={"icon": history.change(old_emoji, category.emoji)},
            )
    return _category_json(category)


@require_POST
def category_delete(request: HttpRequest, trip_id, category_id) -> HttpResponse:
    """Remove a type no expense uses. Deleted expenses that had it simply lose their type."""
    membership = get_membership(request, trip_id, managers_only=True)
    trip = membership.trip
    category = get_object_or_404(Category, pk=category_id, trip=trip)
    with transaction.atomic():
        if lock_trip(trip).is_settled:
            return JsonResponse({"error": _("This trip is settled.")}, status=409)
        used = trip.expenses.filter(category=category).count()
        if used:
            message = ngettext(
                "“%(name)s” is used by %(n)d expense, so it cannot be removed.",
                "“%(name)s” is used by %(n)d expenses, so it cannot be removed.",
                used,
            ) % {"name": category.name, "n": used}
            return JsonResponse({"error": message}, status=409)
        if trip.categories.count() == 1:
            return JsonResponse({"error": _("A trip needs at least one type.")}, status=409)
        history.record(
            trip, membership, "removed", "type", object_id=category.pk, label=category.name
        )
        category.delete()
    return HttpResponse(status=204)


@require_POST
def expense_ai_fill(request: HttpRequest, trip_id) -> HttpResponse:
    """Read one sentence about an expense; answer the form values it states for certain.
    A Member's payer is always their own traveler (``fixed_payer``)."""
    membership = get_membership(request, trip_id, can_add=True)
    trip = membership.trip
    if trip.is_settled:
        return JsonResponse({"error": _("This trip is settled.")}, status=409)
    if not suggest.enabled():
        return JsonResponse({"error": _("Adding with AI is not set up.")}, status=404)
    if not suggest.allowed(request.user.pk):
        return JsonResponse(
            {"error": _("Too many requests. Try again in a few minutes.")}, status=429
        )
    me = membership.linked_traveler
    fixed_payer = not membership.can_manage_expenses
    return JsonResponse(
        ai_fill.fill(trip, request.POST.get("text", ""), me, fixed_payer=fixed_payer)
    )


@require_POST
def description_suggestion(request: HttpRequest, trip_id) -> HttpResponse:
    """A better wording of the description being typed, as JSON {"suggestion": "..."}."""
    trip = get_membership(request, trip_id, can_add=True).trip
    if not suggest.enabled():
        return JsonResponse({"suggestion": ""})
    if not suggest.allowed(request.user.pk):
        return JsonResponse({"suggestion": ""}, status=429)
    return JsonResponse({"suggestion": suggest.suggest(trip, request.POST.get("text", ""))})


def _in_trip(trip, day) -> bool:
    return (not trip.start_date or trip.start_date <= day) and (
        not trip.end_date or day <= trip.end_date
    )


def _initial(request: HttpRequest, membership) -> dict:
    """Sensible defaults: today, the current user as payer, everyone as beneficiary, last currency."""
    trip = membership.trip
    last = trip.expenses.filter(created_by=request.user).order_by("-created_at").first()
    me = membership.linked_traveler
    today = timezone.localdate()
    return {
        "date": today if _in_trip(trip, today) or not trip.start_date else trip.start_date,
        "payer": me or (last.payer if last else None),
        "beneficiaries": list(trip.participants.all()),
        "currency": last.currency if last else trip.base_currency,
        # Food is the most common type on a trip; a trip without it starts on its first type.
        "category": trip.categories.filter(name__iexact="Food & drink").first()
        or trip.categories.first(),
    }


def _trip_days(trip) -> list:
    """Every trip day, for one-tap day chips; empty when the dates are unknown or the trip is long."""
    if not trip.start_date or not trip.end_date or trip.end_date < trip.start_date:
        return []
    count = (trip.end_date - trip.start_date).days + 1
    if count > MAX_DAY_CHIPS:
        return []
    return [trip.start_date + timedelta(days=i) for i in range(count)]


def _payer_only(membership):
    """The one payer a Member may record (their own traveler); None for Owner and Editors."""
    return None if membership.can_manage_expenses else membership.linked_traveler


def _check_payer(request: HttpRequest, membership) -> None:
    """A Member's request with another traveler as payer is refused (403), never changed."""
    payer = request.POST.get("payer")
    if payer and not membership.allowed_payer(payer):
        raise PermissionDenied


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
        "suggestions": suggest.enabled(),
        "emoji_choices": EMOJI_CHOICES,
        "default_emoji": DEFAULT_EMOJI,
    }


def _saved_text(expense) -> str:
    return _("%(what)s, %(amount)s %(currency)s (%(payer)s paid)") % {
        "what": expense,
        "amount": format_amount(expense.amount, expense.currency),
        "currency": expense.currency,
        "payer": expense.payer.name,
    }


def expense_create(request: HttpRequest, trip_id) -> HttpResponse:
    membership = get_membership(request, trip_id, can_add=True)
    if response := locked(request, membership.trip):
        return response
    trip = membership.trip
    if not trip.participants.exists():
        return redirect("people", trip_id=trip.id)
    if request.method == "POST":
        _check_payer(request, membership)
    form = ExpenseForm(
        request.POST or None,
        trip=trip,
        initial=_initial(request, membership),
        payer_only=_payer_only(membership),
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            if response := locked(request, lock_trip(trip)):
                return response
            expense = form.save(commit=False)
            expense.trip = trip
            expense.created_by = expense.updated_by = request.user
            expense.save()
            form.save_m2m()
            history.record_expense(trip, membership, "added", history.fresh_expense(expense.pk))
        messages.success(request, _("Added: %(expense)s") % {"expense": _saved_text(expense)})
        if "add_another" in request.POST:
            return redirect("expense_create", trip_id=trip.id)
        return redirect("trip", trip_id=trip.id)
    return render(request, "expenses/form.html", _form_context(trip, membership, form))


def _back_url(request: HttpRequest, trip_id) -> str:
    """Where an expense page returns to: the trip page it was opened from (``next``), so an
    expense opened on Stats goes back to Stats with its filters; otherwise the Expenses page."""
    target = request.POST.get("next") or request.GET.get("next") or ""
    inside_trip = target.startswith(f"/trips/{trip_id}/")
    if inside_trip and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return target
    return reverse("trip", args=[trip_id])


def expense_edit(request: HttpRequest, trip_id, expense_id) -> HttpResponse:
    """The expense page: the edit form for people who may edit the expense, else read-only.
    On a settled trip it is read-only for everyone."""
    membership = get_membership(request, trip_id)
    trip = membership.trip
    expense = (
        Expense.all_objects.select_related("payer__user", "category", "created_by", "updated_by")
        .filter(pk=expense_id, trip=trip)
        .first()
    )
    if expense is None or expense.deleted_at is not None:
        return _deleted_expense_view(request, membership, expense_id, expense)
    can_edit = membership.can_edit_expense(expense)
    if request.method != "POST" and (trip.is_settled or not can_edit):
        return _expense_view(request, membership, expense)
    if response := locked(request, trip):
        return response
    if not can_edit:
        raise PermissionDenied
    _check_payer(request, membership)
    form = ExpenseForm(
        request.POST or None, instance=expense, trip=trip, payer_only=_payer_only(membership)
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            if response := locked(request, lock_trip(trip)):
                return response
            before = history.expense_snapshot(history.fresh_expense(expense.pk))
            expense = form.save(commit=False)
            expense.updated_by = request.user
            expense.save()
            form.save_m2m()
            history.record_expense(
                trip, membership, "changed", history.fresh_expense(expense.pk), before=before
            )
        messages.success(request, _("Saved: %(expense)s") % {"expense": _saved_text(expense)})
        return redirect(_back_url(request, trip_id))
    context = _form_context(membership.trip, membership, form, expense)
    context["back_url"] = _back_url(request, trip_id)
    return render(request, "expenses/form.html", context)


def expense_delete(request: HttpRequest, trip_id, expense_id) -> HttpResponse:
    membership = get_membership(request, trip_id)
    if response := locked(request, membership.trip):
        return response
    expense = get_object_or_404(Expense, pk=expense_id, trip=membership.trip)
    if not membership.can_edit_expense(expense):
        raise PermissionDenied
    if request.method == "POST":
        with transaction.atomic():
            if response := locked(request, lock_trip(membership.trip)):
                return response
            expense.deleted_at = timezone.now()
            expense.updated_by = request.user
            expense.save(update_fields=["deleted_at", "updated_by", "updated_at"])
            history.record_expense(
                membership.trip, membership, "deleted", history.fresh_expense(expense.pk)
            )
        messages.success(request, _("Deleted: %(expense)s") % {"expense": _saved_text(expense)})
        return redirect(_back_url(request, trip_id))
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
            "back": reverse("expense_edit", args=[trip_id, expense.id])
            + (f"?next={quote(_back_url(request, trip_id))}" if request.GET.get("next") else ""),
            "next": _back_url(request, trip_id),
        },
    )


def _money_facts(trip, amount, currency, count: int, everyone: bool) -> dict:
    """The lines under an expense's amount: its value in the base currency (when a rate exists)
    and each traveler's share. Shared by the read-only page and the deleted-expense page."""
    share = (amount / count).quantize(Decimal("0.01")) if count else Decimal(0)
    base_amount = None
    with suppress(SettlementError):
        base_amount = to_base(amount, currency, trip.base_currency, trip.rate_map())
    # "Everyone (5 travelers)" already gives the count, so the line under it gives only the share.
    if everyone:
        template = _("%(share)s %(currency)s each")
    else:
        template = ngettext(
            "%(n)d traveler · %(share)s %(currency)s each",
            "%(n)d travelers · %(share)s %(currency)s each",
            count,
        )
    split_line = template % {
        "n": count,
        "share": format_amount(share, currency),
        "currency": currency,
    }
    return {"base_amount": base_amount, "split_line": split_line}


def _expense_view(request: HttpRequest, membership, expense) -> HttpResponse:
    """The expense page read-only: the same values as the form, with no Save or Delete."""
    trip = membership.trip
    if trip.is_settled:
        reason = _("This trip is settled, so its expenses are locked.")
    elif membership.is_viewer:
        reason = _(
            "Your account is not linked to a traveler, so you can view expenses but not "
            "change them. The trip Owner can link it."
        )
    else:
        reason = _who_may_change(expense.payer)
    beneficiaries = list(expense.beneficiaries.all())
    everyone = {p.pk for p in beneficiaries} == {p.pk for p in trip.participants.all()}
    facts = _money_facts(trip, expense.amount, expense.currency, len(beneficiaries), everyone)
    return render(
        request,
        "expenses/detail.html",
        {
            "trip": trip,
            "membership": membership,
            "expense": expense,
            "beneficiaries": beneficiaries,
            "names": [p.name for p in beneficiaries],
            "everyone": everyone,
            **facts,
            "reason": reason,
            "back_url": _back_url(request, trip.id),
        },
    )


def _deleted_expense_view(request: HttpRequest, membership, expense_id, row) -> HttpResponse:
    """A deleted expense, from its last History values, with Restore for people allowed to.

    ``row`` is the deleted expense, or None when it was erased (with its payer, as today); its
    History entries then still read, but it can no longer be restored."""
    trip = membership.trip
    values = history.last_expense_values(trip, expense_id, row)
    if values is None or request.method != "GET":
        raise Http404
    deleted = (
        trip.history.filter(object_type="expense", object_id=str(expense_id), action="deleted")
        .select_related("actor")
        .first()
    )
    can_restore = row is not None and membership.can_edit_expense(row)
    if row is None:
        reason = _("%(name)s was removed from the trip, so this expense cannot be restored.") % {
            "name": values["payer"]
        }
    elif trip.is_settled:
        reason = _("This trip is settled, so its expenses are locked.")
    elif not can_restore:
        reason = _who_may_change(row.payer, restore=True)
    else:
        reason = ""
    everyone = set(values["for_ids"]) == {str(p.pk) for p in trip.participants.all()}
    category = trip.categories.filter(pk=values["type_id"]).first() if values["type_id"] else None
    amount = Decimal(values["amount"])
    facts = _money_facts(trip, amount, values["currency"], len(values["for_ids"]), everyone)
    return render(
        request,
        "expenses/deleted.html",
        {
            "trip": trip,
            "membership": membership,
            "expense_id": expense_id,
            "values": values,
            "title": values["description"] or values["type"],
            "emoji": category.emoji if category else "📦",
            "names": values["for"],
            "amount": amount,
            **facts,
            "day": date.fromisoformat(values["date"]),
            "everyone": everyone,
            "deleted": deleted,
            "reason": reason,
            "can_restore": can_restore and not trip.is_settled,
            "back_url": _back_url(request, trip.id),
        },
    )


@require_POST
def expense_restore(request: HttpRequest, trip_id, expense_id) -> HttpResponse:
    """Bring a deleted expense back with its last History values. Whoever may edit it may
    restore it; refused on a settled trip; a second tap changes nothing."""
    membership = get_membership(request, trip_id)
    trip = membership.trip
    expense = Expense.all_objects.filter(pk=expense_id, trip=trip).first()
    if expense is None:
        if not trip.history.filter(object_type="expense", object_id=str(expense_id)).exists():
            raise Http404
        messages.error(request, _("This expense can no longer be restored."))
        return redirect("expense_edit", trip_id=trip.id, expense_id=expense_id)
    if not membership.can_edit_expense(expense):
        raise PermissionDenied
    if response := locked(request, trip):
        return response
    try:
        restored = history.restore_expense(trip, expense_id, by=membership)
    except history.RestoreRefused as refused:
        messages.error(request, str(refused))
        return redirect("expense_edit", trip_id=trip.id, expense_id=expense_id)
    if restored:
        messages.success(
            request,
            _("Restored: %(expense)s")
            % {"expense": _saved_text(history.fresh_expense(expense_id))},
        )
    return redirect("expense_edit", trip_id=trip.id, expense_id=expense_id)


def _who_may_change(payer, *, restore: bool = False) -> str:
    """The read-only notice for a Member: who besides the Owner and Editors may change (or
    restore) it."""
    if payer.user is None:
        if restore:
            return _("Only the Owner or an Editor can restore this expense.")
        return _("Only the Owner or an Editor can change this expense.")
    account = payer.user.display_name
    name = account if account == payer.name else f"{account} ({payer.name})"
    if restore:
        return _("Only %(name)s, the Owner or an Editor can restore this expense.") % {"name": name}
    return _("Only %(name)s, the Owner or an Editor can change this expense.") % {"name": name}


def _filter_summary(filters: dict) -> list[str]:
    """The active filters in a few words, for the collapsed filter card: "Person A · Food"."""
    parts = []
    if filters.get("person"):
        parts.append(filters["person"].name)
    if filters.get("payer"):
        parts.append(_("paid by %(name)s") % {"name": filters["payer"].name})
    if filters.get("category"):
        parts.append(filters["category"].name)
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
        # Expenses opened from this page come back here, with the same filters.
        return_to=request.path + (f"?{query.urlencode()}" if query else ""),
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
