from datetime import datetime, time, timedelta
from itertools import groupby

from django.db.models.functions import TruncDate
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from . import history
from .access import get_membership
from .pagination import DayPage


def history_page(request: HttpRequest, trip_id) -> HttpResponse:
    """What changed in the trip, newest first, grouped by day. Open to every member."""
    membership = get_membership(request, trip_id)
    trip = membership.trip
    entries = trip.history.all()
    q = request.GET.get("q", "").strip()[:100]
    for word in q.lower().split():
        entries = entries.filter(search_text__icontains=word)  # The search runs in the database.
    zone = timezone.get_current_timezone()
    all_days = list(
        entries.annotate(day=TruncDate("created_at", tzinfo=zone))
        .values_list("day", flat=True)
        .distinct()
        .order_by("-day")
    )
    page = DayPage(request, all_days)
    days = []
    if page.days:
        newest, oldest = page.days[0], page.days[-1]
        start = timezone.make_aware(datetime.combine(oldest, time.min))
        end = timezone.make_aware(datetime.combine(newest + timedelta(days=1), time.min))
        shown = list(entries.filter(created_at__gte=start, created_at__lt=end))
        for entry in shown:
            entry.text = history.describe(entry)
        days = [
            (day, list(items), None)
            for day, items in groupby(shown, key=lambda e: timezone.localtime(e.created_at).date())
        ]
    return render(
        request,
        "trips/history.html",
        {
            "trip": trip,
            "membership": membership,
            "page": page,
            "days": days,
            "multi_year": len({d.year for d in all_days}) > 1,
            "q": q,
            "tab": "history",
        },
    )
