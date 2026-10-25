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
    expense = Expense.objects.create(
        trip=trip,
        date=date(2026, 6, 1),
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
    ]
    for url in urls:
        assert client.get(url).status_code == 404, url


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


def test_balances_page_puts_each_payment_on_the_payer_row(owner_client, trip):
    owner_p, friend = trip.participants.all()
    add_expense(trip, owner_p, [owner_p, friend], "30")
    response = owner_client.get(reverse("summary", args=[trip.id]))
    rows = response.context["summary"]["rows"]
    assert [r["person"] for r in rows] == [owner_p, friend]
    assert rows[1]["pays"] == [{"person": owner_p, "amount": Decimal("15.00")}]
    html = response.content.decode()
    assert "Pays Owner 15.00" in html
    assert "Friend pays you 15.00" in html


def test_balances_why_shows_both_directions_for_a_debtor(client, trip, make_user):
    owner_p, friend = trip.participants.all()
    friend_user = make_user("friend")
    TripMember.objects.create(trip=trip, user=friend_user)
    friend.user = friend_user
    friend.save()
    add_expense(trip, friend, [owner_p, friend], "20")
    add_expense(trip, owner_p, [friend], "50")
    client.force_login(friend_user)
    response = client.get(reverse("summary", args=[trip.id]))
    me = response.context["summary"]["me"]
    # Friend paid 10 for Owner; Owner paid 50 for Friend; so Friend owes 40.
    assert (me["for_others"], me["from_others"], me["row"].balance) == (
        Decimal("10.00"),
        Decimal("50.00"),
        Decimal("-40.00"),
    )
    assert "Pay Owner 40.00" in response.content.decode()


def test_expenses_tab_shows_the_trip_dashboard(owner_client, trip):
    owner_p, friend = trip.participants.all()
    add_expense(trip, owner_p, [owner_p, friend], "30")
    response = owner_client.get(reverse("trip", args=[trip.id]))
    html = response.content.decode()
    for label in ("Your cost", "Trip total", "Where the money went", "By type"):
        assert label in html
    # The trip has no dates, so every day is a trip day.
    assert response.context["today_total"] is not None


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
