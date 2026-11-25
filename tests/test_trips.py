import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from django.urls import reverse

from apps.expenses.models import Expense
from apps.trips.models import ExchangeRate, Participant, Trip, TripMember
from apps.trips.summary import trip_settlement
from apps.trips.templatetags.ui import format_amount

pytestmark = pytest.mark.django_db
SHEET = Path(__file__).parent / "fixtures" / "sheets" / "vn_20260531.json"


def add_expense(trip, payer, beneficiaries, amount, currency="USD", **extra):
    extra.setdefault("date", date(2026, 6, 1))
    expense = Expense.objects.create(
        trip=trip,
        payer=payer,
        amount=Decimal(amount),
        currency=currency,
        **extra,
    )
    expense.beneficiaries.set(beneficiaries)
    return expense


def test_creating_a_trip_makes_the_creator_owner_and_traveller(owner_client, owner):
    response = owner_client.post(
        reverse("trip_create"), {"name": "Bangkok", "base_currency": "USD"}
    )
    trip = Trip.objects.get(name="Bangkok")
    assert response.status_code == 302
    assert TripMember.objects.get(trip=trip, user=owner).is_owner
    assert trip.participants.get().user == owner


def test_country_is_picked_from_the_world_list(owner_client):
    form = owner_client.get(reverse("trip_create")).content.decode()
    assert '<option value="KH">Cambodia</option>' in form
    assert '<option value="VN">Vietnam</option>' in form
    owner_client.post(
        reverse("trip_create"), {"name": "Hanoi", "country": "VN", "base_currency": "USD"}
    )
    trip = Trip.objects.get(name="Hanoi")
    assert trip.country.code == "VN"
    assert "Vietnam ·" in owner_client.get(reverse("trip", args=[trip.id])).content.decode()
    owner_client.post(
        reverse("trip_create"), {"name": "Nowhere", "country": "Vietnam", "base_currency": "USD"}
    )
    assert not Trip.objects.filter(name="Nowhere").exists()


def test_non_member_gets_404_on_every_trip_page(client, trip, make_user):
    client.force_login(make_user("stranger"))
    expense = add_expense(trip, *trip.participants.all()[:1], trip.participants.all(), "10")
    person = trip.participants.first()
    urls = [
        reverse("trip", args=[trip.id]),
        reverse("summary", args=[trip.id]),
        reverse("people", args=[trip.id]),
        reverse("trip_settings", args=[trip.id]),
        reverse("expense_create", args=[trip.id]),
        reverse("expense_edit", args=[trip.id, expense.id]),
        reverse("expense_delete", args=[trip.id, expense.id]),
        reverse("participant_create", args=[trip.id]),
        reverse("participant_edit", args=[trip.id, person.id]),
        reverse("trip_delete", args=[trip.id]),
        reverse("report", args=[trip.id]),
        reverse("report_export", args=[trip.id, "csv"]),
    ]
    for url in urls:
        assert client.get(url).status_code == 404, url
    for name in ("trip_settle", "trip_reopen"):
        assert client.post(reverse(name, args=[trip.id])).status_code == 404, name


def test_member_can_record_expenses_but_not_manage_the_trip(client, trip, make_user):
    member = make_user("member")
    TripMember.objects.create(trip=trip, user=member)
    client.force_login(member)
    payer = trip.participants.first()
    response = client.post(
        reverse("expense_create", args=[trip.id]),
        {
            "amount": "12.50",
            "currency": "USD",
            "category": "food",
            "payer": payer.id,
            "beneficiaries": [p.id for p in trip.participants.all()],
            "date": "2026-06-01",
        },
    )
    assert response.status_code == 302
    expense = trip.expenses.get()
    assert expense.created_by == member
    assert client.get(reverse("trip_settings", args=[trip.id])).status_code == 403
    assert client.get(reverse("trip_delete", args=[trip.id])).status_code == 403
    assert (
        client.post(reverse("participant_create", args=[trip.id]), {"name": "X"}).status_code == 403
    )
    assert not trip.participants.filter(name="X").exists()


def test_expense_cannot_use_a_person_from_another_trip(owner_client, owner, trip, make_trip):
    other = make_trip(owner, name="Other trip", people=("Outsider",))
    outsider = other.participants.get()
    response = owner_client.post(
        reverse("expense_create", args=[trip.id]),
        {
            "amount": "5",
            "currency": "USD",
            "category": "food",
            "payer": outsider.id,
            "beneficiaries": [outsider.id],
            "date": "2026-06-01",
        },
    )
    assert response.status_code == 200
    assert not trip.expenses.exists()


def test_currency_needs_an_exchange_rate(owner_client, trip):
    payload = {
        "amount": "74000",
        "currency": "VND",
        "category": "transport",
        "payer": trip.participants.first().id,
        "beneficiaries": [p.id for p in trip.participants.all()],
        "date": "2026-06-01",
    }
    assert owner_client.post(reverse("expense_create", args=[trip.id]), payload).status_code == 200
    owner_client.post(reverse("rate_save", args=[trip.id]), {"currency": "VND", "rate": "26200"})
    assert owner_client.post(reverse("expense_create", args=[trip.id]), payload).status_code == 302


def test_deleted_expense_is_kept_but_left_out_of_totals(owner_client, trip):
    owner_p, friend = trip.participants.all()
    expense = add_expense(trip, owner_p, [owner_p, friend], "20")
    owner_client.post(reverse("expense_delete", args=[trip.id, expense.id]))
    assert Expense.all_objects.get(pk=expense.pk).deleted_at is not None
    assert all(p.balance == 0 for p in trip_settlement(trip).people)


def test_balances_page_shows_amounts_not_who_pays_whom(owner_client, trip):
    owner_p, friend = trip.participants.all()
    add_expense(trip, owner_p, [owner_p, friend], "30")
    response = owner_client.get(reverse("summary", args=[trip.id]))
    rows = response.context["summary"]["rows"]
    assert [(r["person"], r["row"].balance) for r in rows] == [
        (owner_p, Decimal("15.00")),
        (friend, Decimal("-15.00")),
    ]
    html = response.content.decode()
    assert "You are owed" in html
    assert "is owed" in html and "owes" in html
    assert "is owed" in html and "owes" in html
    for old in ("Pays Owner", "pays you", "get back"):
        assert old not in html


def test_balances_breakdown_adds_up_to_the_balance(client, trip, make_user):
    owner_p, friend = trip.participants.all()
    friend_user = make_user("friend")
    TripMember.objects.create(trip=trip, user=friend_user)
    friend.user = friend_user
    friend.save()
    add_expense(trip, friend, [owner_p, friend], "20")
    add_expense(trip, owner_p, [friend], "50")
    client.force_login(friend_user)
    response = client.get(reverse("summary", args=[trip.id]))
    row = response.context["summary"]["me"]["row"]
    # Friend paid 20 and has a share of 10 + 50 = 60, so Friend owes 40.
    assert (row.paid, row.responsible_for, row.balance) == (
        Decimal("20.00"),
        Decimal("60.00"),
        Decimal("-40.00"),
    )
    assert "You owe" in response.content.decode()


def test_expenses_tab_highlights_the_total_spent(owner_client, trip):
    owner_p, friend = trip.participants.all()
    add_expense(trip, owner_p, [owner_p, friend], "30")
    response = owner_client.get(reverse("trip", args=[trip.id]))
    html = response.content.decode()
    for label in ("Total spent", "Your share", "You are owed", "Add expense"):
        assert label in html
    assert "Where the money went" not in html
    # The trip has no dates, so no day is "today".
    assert "today_total" not in response.context


def test_spending_filters_by_person_and_shows_their_share(owner_client, trip):
    owner_p, friend = trip.participants.all()
    add_expense(trip, owner_p, [owner_p, friend], "30", category="food")
    add_expense(trip, owner_p, [owner_p], "12", category="transport")
    url = reverse("report", args=[trip.id])
    everyone = owner_client.get(url).context["report"]
    assert everyone["total"] == Decimal("42.00")
    friend_view = owner_client.get(url, {"person": friend.id}).context["report"]
    assert len(friend_view["rows"]) == 1
    assert friend_view["share"] == Decimal("15.00")
    assert friend_view["by_category"][0]["amount"] == Decimal("15.00")
    food = owner_client.get(url, {"category": "food"}).context["report"]
    assert food["total"] == Decimal("30.00")


def test_spending_share_follows_the_sponsor(owner_client, trip):
    owner_p, friend = trip.participants.all()
    friend.sponsors.set([owner_p])
    add_expense(trip, friend, [owner_p, friend], "30")
    report = owner_client.get(reverse("report", args=[trip.id]), {"person": owner_p.id}).context
    # Owner covers Friend, so Owner's share is the whole 30, matching the Balances page.
    assert report["report"]["share"] == Decimal("30.00")
    assert trip_settlement(trip).people[0].responsible_for == Decimal("30.00")


def test_export_keeps_the_filters(owner_client, trip):
    owner_p, friend = trip.participants.all()
    add_expense(trip, owner_p, [owner_p, friend], "30", description="Taxi", category="transport")
    add_expense(trip, owner_p, [owner_p], "12", description="Lunch", category="food")
    url = reverse("report_export", args=[trip.id, "csv"])
    csv_text = owner_client.get(url, {"category": "transport"}).content.decode("utf-8-sig")
    assert "Taxi" in csv_text and "Lunch" not in csv_text
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("Date,Description,Type,Paid by")
    xlsx = owner_client.get(reverse("report_export", args=[trip.id, "xlsx"]))
    assert xlsx["Content-Type"].startswith("application/vnd.openxmlformats")
    assert xlsx.content[:2] == b"PK"  # An .xlsx file is a zip archive.
    assert owner_client.get(reverse("report_export", args=[trip.id, "pdf"])).status_code == 404


def test_long_lists_load_more_and_never_split_a_day(owner_client, trip):
    owner_p, friend = trip.participants.all()
    for i in range(30):
        add_expense(trip, owner_p, [owner_p, friend], str(i + 1), date=date(2026, 6, 1 + i // 10))
    url = reverse("trip", args=[trip.id])
    first = owner_client.get(url)
    page = first.context["page"]
    # Days of 10 rows: a page takes whole days until it has 25 rows, so 30 rows on page 1.
    assert [len(items) for _day, items, _total in page.days] == [10, 10, 10]
    assert not page.has_next()
    for _ in range(30):
        add_expense(trip, owner_p, [owner_p], "1", date=date(2026, 7, 1))
    page = owner_client.get(url).context["page"]
    assert page.has_next() and page.end_index == 30
    assert "Load more" in owner_client.get(url).content.decode()
    second = owner_client.get(url, {"page": 2}).context["page"]
    assert second.end_index == 60


def test_today_is_hidden_outside_the_trip_dates(owner_client, trip):
    owner_p, friend = trip.participants.all()
    trip.start_date, trip.end_date = date(2020, 1, 1), date(2020, 1, 5)
    trip.save()
    add_expense(trip, owner_p, [owner_p, friend], "30")
    response = owner_client.get(reverse("trip", args=[trip.id]))
    assert "today_total" not in response.context


def test_sponsor_chain_is_rejected(owner_client, trip):
    owner_p, friend = trip.participants.all()
    child = Participant.objects.create(trip=trip, name="Child")
    child.sponsors.set([friend])
    response = owner_client.post(
        reverse("participant_edit", args=[trip.id, friend.id]),
        {"name": "Friend", "sponsors": [owner_p.id]},
    )
    assert response.status_code == 200
    assert not friend.sponsors.exists()


def test_person_used_in_an_expense_cannot_be_removed(owner_client, trip):
    owner_p, friend = trip.participants.all()
    add_expense(trip, owner_p, [friend], "8")
    owner_client.post(reverse("participant_delete", args=[trip.id, friend.id]))
    assert Participant.objects.filter(pk=friend.pk).exists()


def test_real_sheet_through_the_database_matches_the_spreadsheet(owner, make_trip):
    data = json.loads(SHEET.read_text())
    trip = make_trip(owner, people=data["participants"])
    people = {p.name: p for p in trip.participants.all()}
    for currency, rate in data["rates"].items():
        ExchangeRate.objects.create(trip=trip, currency=currency, rate=Decimal(rate))
    for name, sponsors in data["sponsors"].items():
        people[name].sponsors.set([people[s] for s in sponsors if s != name])
    for e in data["expenses"]:
        if Decimal(e["amount"]) > 0:
            add_expense(
                trip,
                people[e["payer"]],
                [people[b] for b in e["beneficiaries"]],
                e["amount"],
                e["currency"],
            )
    by_id = {p.id: p.name for p in people.values()}
    for row in trip_settlement(trip).people:
        expected = Decimal(str(data["expected_balances"][by_id[row.participant]]))
        assert abs(row.balance - expected) <= Decimal("0.01")


def test_money_shows_whole_units_without_cents():
    assert format_amount(Decimal("600000"), "VND") == "600,000"
    assert format_amount(Decimal("42.5"), "USD") == "42.50"
    assert format_amount(Decimal("12.5"), "VND") == "12.50"


def expense_payload(trip, **extra):
    return {
        "amount": "10",
        "currency": "USD",
        "category": "food",
        "payer": trip.participants.first().id,
        "beneficiaries": [p.id for p in trip.participants.all()],
        "date": "2026-06-01",
        **extra,
    }


def test_amount_accepts_thousand_separators(owner_client, trip):
    owner_client.post(reverse("rate_save", args=[trip.id]), {"currency": "VND", "rate": "26200"})
    payload = expense_payload(trip, amount="450,000", currency="VND")
    assert owner_client.post(reverse("expense_create", args=[trip.id]), payload).status_code == 302
    assert trip.expenses.get().amount == Decimal("450000")


def test_other_date_chip_uses_the_typed_date(owner_client, trip):
    payload = expense_payload(trip, date="other", date_other="2026-05-20")
    assert owner_client.post(reverse("expense_create", args=[trip.id]), payload).status_code == 302
    assert str(trip.expenses.get().date) == "2026-05-20"


def test_owner_adds_a_traveller_on_its_own_page(owner_client, trip):
    url = reverse("participant_create", args=[trip.id])
    response = owner_client.post(url, {"name": "Grandma", "add_another": ""})
    assert response.status_code == 302 and response.url == url
    assert trip.participants.filter(name="Grandma").exists()


def test_read_pages_may_be_stored_by_the_service_worker(owner_client, trip):
    owner_p, friend = trip.participants.all()
    add_expense(trip, owner_p, [owner_p, friend], "30")
    for name in ("trip", "summary", "report", "people"):
        first = owner_client.get(reverse(name, args=[trip.id]))
        second = owner_client.get(reverse(name, args=[trip.id]))
        assert first["X-SW-Cache"] == "page", name
        assert first["Cache-Control"] == "private, no-cache"
        # The CSRF token differs per response, but it is left out of the hash.
        assert first["X-Page-Hash"] == second["X-Page-Hash"], name
    form = owner_client.get(reverse("expense_create", args=[trip.id]))
    assert "X-SW-Cache" not in form


def test_page_with_a_one_time_message_is_not_stored(owner_client, trip):
    owner_p, friend = trip.participants.all()
    response = owner_client.post(
        reverse("expense_create", args=[trip.id]),
        {
            "amount": "10",
            "currency": "USD",
            "category": "food",
            "payer": owner_p.id,
            "beneficiaries": [owner_p.id, friend.id],
            "date": "2026-06-01",
        },
        follow=True,
    )
    assert "Added:" in response.content.decode()
    assert "X-SW-Cache" not in response
    assert response["Cache-Control"] == "private, no-store"


def test_service_worker_is_public_and_versioned(client):
    response = client.get("/sw.js")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/javascript")
    assert 'const VERSION = "' in response.content.decode()
    assert response["Cache-Control"] == "no-cache"


def test_spending_share_matches_balances_and_its_rows(owner_client, trip):
    owner_p, friend = trip.participants.all()
    third = Participant.objects.create(trip=trip, name="Third")
    people = [owner_p, friend, third]
    for amount in ("100", "10", "20.01"):
        add_expense(trip, owner_p, people, amount)
    balances = {s.participant: s.responsible_for for s in trip_settlement(trip).people}
    for person in people:
        report = owner_client.get(reverse("report", args=[trip.id]), {"person": person.id})
        data = report.context["report"]
        assert data["share"] == balances[person.id], person
        assert sum(r.share for r in data["rows"]) == data["share"]
        assert sum(d["amount"] for d in data["by_day"]) == data["share"]


def test_spending_for_a_covered_person_lists_their_expenses(owner_client, trip):
    owner_p, friend = trip.participants.all()
    friend.sponsors.set([owner_p])
    add_expense(trip, owner_p, [owner_p, friend], "30")
    response = owner_client.get(reverse("report", args=[trip.id]), {"person": friend.id})
    assert len(response.context["report"]["rows"]) == 1
    html = response.content.decode()
    assert "Friend is covered by Owner." in html
    assert "No expenses" not in html


def test_owner_can_delete_a_trip_with_expenses(owner_client, trip):
    owner_p, friend = trip.participants.all()
    expense = add_expense(trip, owner_p, [owner_p, friend], "30")
    expense.deleted_at = expense.created_at  # A deleted expense is kept in the database too.
    expense.save()
    add_expense(trip, friend, [owner_p, friend], "10")
    response = owner_client.post(reverse("trip_delete", args=[trip.id]))
    assert response.status_code == 302
    assert not Trip.objects.filter(pk=trip.pk).exists()
    assert not Expense.all_objects.filter(trip_id=trip.pk).exists()


def test_owner_marks_a_trip_settled_and_reopens_it(owner_client, trip):
    owner_p, friend = trip.participants.all()
    add_expense(trip, owner_p, [owner_p, friend], "30")
    page = owner_client.get(reverse("summary", args=[trip.id])).content.decode()
    assert "Mark as settled" in page and "hx-confirm" in page
    owner_client.post(reverse("trip_settle", args=[trip.id]))
    trip.refresh_from_db()
    assert trip.is_settled
    page = owner_client.get(reverse("summary", args=[trip.id])).content.decode()
    assert "Settled on" in page and "Reopen trip" in page and "Mark as settled" not in page
    assert "You were owed" in page and "was owed" in page and "You are owed" not in page
    assert " by " not in page.split("Settled on", 1)[1].split("<", 1)[0]
    # The balances stay as a record; settling records no payment.
    assert trip_settlement(trip).people[0].balance == Decimal("15.00")
    home = owner_client.get(reverse("home")).content.decode()
    assert "Settled" in home
    owner_client.post(reverse("trip_reopen", args=[trip.id]))
    trip.refresh_from_db()
    assert not trip.is_settled


def test_settled_trip_locks_everything_that_changes_the_numbers(owner_client, trip):
    owner_p, friend = trip.participants.all()
    expense = add_expense(trip, owner_p, [owner_p, friend], "30")
    owner_client.post(reverse("trip_settle", args=[trip.id]))
    for url in (
        reverse("expense_create", args=[trip.id]),
        reverse("expense_edit", args=[trip.id, expense.id]),
        reverse("expense_delete", args=[trip.id, expense.id]),
        reverse("participant_create", args=[trip.id]),
        reverse("participant_edit", args=[trip.id, friend.id]),
        reverse("participant_delete", args=[trip.id, friend.id]),
    ):
        response = owner_client.post(url, {"name": "X", "amount": "1"})
        assert response.status_code == 302, url
        assert response["Location"] == reverse("trip", args=[trip.id]), url
    assert (
        owner_client.post(
            reverse("rate_save", args=[trip.id]), {"currency": "VND", "rate": "26000"}
        ).status_code
        == 302
    )
    assert not trip.rates.exists()
    expense.refresh_from_db()
    assert expense.deleted_at is None and trip.participants.count() == 2
    page = owner_client.get(reverse("trip", args=[trip.id])).content.decode()
    assert "Add expense" not in page
    assert reverse("expense_edit", args=[trip.id, expense.id]) not in page


def test_only_the_owner_settles_or_reopens(client, trip, make_user):
    member = make_user("member")
    TripMember.objects.create(trip=trip, user=member)
    client.force_login(member)
    assert client.post(reverse("trip_settle", args=[trip.id])).status_code == 403
    assert "Mark as settled" not in client.get(reverse("summary", args=[trip.id])).content.decode()
