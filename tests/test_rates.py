"""Exchange rates on the New trip page, the country -> currency map and the market rate service."""

import io
import json
from datetime import date
from decimal import Decimal
from urllib.error import URLError as urllib_error

import pytest
from django.urls import reverse

from apps.trips import rates
from apps.trips.country_currency import COUNTRY_CURRENCY, currency_for
from apps.trips.currencies import CURRENCIES
from apps.trips.models import HistoryEntry, Trip

SUCCESS = {
    "result": "success",
    "time_last_update_utc": "Sat, 28 Nov 2026 00:02:31 +0000",
    "rates": {"USD": 1, "KHR": 4068.37, "VND": 25840.1, "THB": 33.9349, "EUR": 0.86213},
}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def service(db, monkeypatch):
    """Replace the HTTP call: record each URL and answer with ``reply["body"]`` (or raise it)."""
    calls, reply = [], {"body": SUCCESS}

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        body = reply["body"]
        if isinstance(body, Exception):
            raise body
        return FakeResponse(body if isinstance(body, bytes) else json.dumps(body).encode())

    monkeypatch.setattr(rates, "urlopen", fake_urlopen)
    return calls, reply


# --- Country -> currency -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "country, currency",
    [
        ("KH", "KHR"),
        ("VN", "VND"),
        ("TH", "THB"),
        ("LA", "LAK"),
        ("US", "USD"),
        ("FR", "EUR"),
        ("GB", "GBP"),
        ("JP", "JPY"),
        ("CN", "CNY"),
        ("IN", "INR"),
        ("PA", "USD"),
        ("kh", "KHR"),
        ("AQ", ""),
        ("", ""),
    ],
)
def test_country_currency(country, currency):
    assert currency_for(country) == currency


def test_every_country_offered_has_a_currency_in_the_dropdowns():
    from django_countries.data import COUNTRIES

    assert set(COUNTRIES) - set(COUNTRY_CURRENCY) == {"AQ"}
    assert set(COUNTRY_CURRENCY.values()) <= set(CURRENCIES)
    assert CURRENCIES[:3] == ["USD", "KHR", "VND"]  # The common ones stay first.
    assert len(CURRENCIES) == len(set(CURRENCIES))


# --- The rates module --------------------------------------------------------------------------


def test_market_rate_success(service, settings):
    calls, _reply = service
    market = rates.market_rate("USD", "KHR")
    assert market == rates.MarketRate(rate=Decimal("4068"), day=date(2026, 11, 28))
    assert calls == [(f"{settings.EXCHANGE_RATES_URL}/USD", rates.TIMEOUT_SECONDS)]
    assert rates.TIMEOUT_SECONDS == 4


def test_one_call_per_base_currency_per_day(service):
    calls, _reply = service
    assert rates.market_rate("USD", "KHR").rate == Decimal("4068")
    assert rates.market_rate("USD", "THB").rate == Decimal("33.93")
    assert rates.market_rate("USD", "VND").rate == Decimal("25840")
    assert len(calls) == 1


@pytest.mark.parametrize(
    "body",
    [
        urllib_error("timed out"),
        TimeoutError(),
        OSError("network unreachable"),
        b"<html>not json</html>",
        {"result": "error", "error-type": "unsupported-code"},
        {"result": "success", "rates": "none"},
        {"result": "success", "rates": {"KHR": 4000}},  # No update time.
    ],
)
def test_service_failure_gives_none(service, body):
    service[1]["body"] = body
    assert rates.market_rate("USD", "KHR") is None


def test_a_failure_is_remembered_for_a_while(service):
    calls, reply = service
    reply["body"] = TimeoutError()
    assert rates.market_rate("USD", "KHR") is None
    assert rates.market_rate("USD", "KHR") is None
    assert len(calls) == 1


def test_unknown_currency_gives_none(service):
    assert rates.market_rate("USD", "XYZ") is None


def test_empty_url_turns_the_rates_off(service, settings):
    settings.EXCHANGE_RATES_URL = ""
    assert rates.market_rate("USD", "KHR") is None
    assert service[0] == []


@pytest.mark.parametrize(
    "rate, shown",
    [
        ("4068.37", "4068"),
        ("25840.5", "25841"),
        ("100", "100"),
        ("33.9349", "33.93"),
        ("1.005", "1.01"),
        ("0.86213", "0.8621"),
        ("0.000245812", "0.000246"),
    ],
)
def test_rounding(rate, shown):
    assert str(rates.rounded(Decimal(rate))) == shown


# --- The suggestion endpoint -------------------------------------------------------------------


def suggestion(client, **params):
    return client.get(reverse("rate_suggestion"), params)


def test_suggestion_needs_login(client, service):
    response = suggestion(client, country="KH", base="USD")
    assert response.status_code == 302
    assert service[0] == []


def test_suggestion_for_a_country(owner_client, service):
    response = suggestion(owner_client, country="KH", base="USD")
    assert response.json() == {"currency": "KHR", "rate": "4068", "day": "28 Nov 2026"}


def test_suggestion_for_a_currency(owner_client, service):
    response = suggestion(owner_client, currency="THB", base="USD")
    assert response.json() == {"currency": "THB", "rate": "33.93", "day": "28 Nov 2026"}


@pytest.mark.parametrize(
    "params",
    [
        {"country": "US", "base": "USD"},  # The country's currency is the base currency.
        {"country": "ZZ", "base": "USD"},  # Unknown country.
        {"country": "AQ", "base": "USD"},  # No currency.
        {"country": "KH", "base": "XXX"},  # Unknown base.
        {"currency": "USD", "base": "USD"},
        {"base": "USD"},
    ],
)
def test_no_suggestion(owner_client, service, params):
    assert suggestion(owner_client, **params).json()["currency"] == ""
    assert service[0] == []


def test_service_down_still_suggests_the_currency(owner_client, service):
    service[1]["body"] = TimeoutError()
    response = suggestion(owner_client, country="VN", base="USD")
    assert response.json() == {"currency": "VND", "rate": None, "day": None}


def test_suggestions_are_rate_limited(owner_client, service, monkeypatch):
    monkeypatch.setattr(rates, "LIMIT", 2)
    assert suggestion(owner_client, country="KH", base="USD").status_code == 200
    assert suggestion(owner_client, country="KH", base="USD").status_code == 200
    assert suggestion(owner_client, country="KH", base="USD").status_code == 429


# --- New trip with rate rows -------------------------------------------------------------------


def new_trip(client, rows, **fields):
    data = {
        "name": "Siem Reap",
        "country": "KH",
        "start_date": "2026-12-03",
        "end_date": "2026-12-07",
        "base_currency": "USD",
        "rates-TOTAL_FORMS": str(len(rows)),
        "rates-INITIAL_FORMS": "0",
        **fields,
    }
    for i, (currency, rate) in enumerate(rows):
        data[f"rates-{i}-currency"] = currency
        data[f"rates-{i}-rate"] = rate
    return client.post(reverse("trip_create"), data)


def test_new_trip_page_has_one_empty_rate_row(owner_client):
    html = owner_client.get(reverse("trip_create")).content.decode()
    assert 'name="rates-TOTAL_FORMS" value="1"' in html
    assert 'name="rates-0-currency"' in html and 'name="rates-0-rate"' in html
    assert 'type="date" name="start_date"' in html  # Works without JavaScript.
    assert "Rates by ExchangeRate-API" in html  # The note template, for the market rates.


def test_new_trip_saves_its_rates_and_history(owner_client, owner):
    response = new_trip(owner_client, [("KHR", "4068"), ("", ""), ("THB", "33.93")])
    assert response.status_code == 302
    trip = Trip.objects.get(name="Siem Reap")
    assert trip.start_date == date(2026, 12, 3) and trip.end_date == date(2026, 12, 7)
    assert trip.rate_map() == {"KHR": Decimal("4068"), "THB": Decimal("33.93")}
    entries = HistoryEntry.objects.filter(trip=trip, object_type="rate").order_by("object_label")
    assert [(e.action, e.object_label, e.actor_id) for e in entries] == [
        ("added", "KHR", owner.pk),
        ("added", "THB", owner.pk),
    ]
    assert entries[0].changes["rate"]["new"] == "1 USD = 4,068 KHR"


def test_a_removed_row_number_is_skipped(owner_client):
    data_rows = [("KHR", "4068")]
    response = new_trip(owner_client, data_rows, **{"rates-TOTAL_FORMS": "3"})
    assert response.status_code == 302
    assert Trip.objects.get().rate_map() == {"KHR": Decimal("4068")}


@pytest.mark.parametrize(
    "rows, error",
    [
        ([("USD", "1")], "This is already the trip&#x27;s base currency."),
        ([("KHR", "4000"), ("KHR", "4100")], "This currency already has a rate."),
        ([("KHR", "0")], "Enter a rate above zero."),
        ([("KHR", "-5")], "Enter a rate above zero."),
        ([("KHR", "abc")], "Enter a number."),
        ([("KHR", "")], "This field is required."),
        ([("", "4000")], "This field is required."),
        ([("XYZ", "4000")], "Select a valid choice."),
    ],
)
def test_bad_rate_rows_create_nothing(owner_client, rows, error):
    response = new_trip(owner_client, rows)
    assert response.status_code == 200
    assert error in response.content.decode()
    assert not Trip.objects.exists()


def test_trip_errors_and_rate_errors_show_together(owner_client):
    response = new_trip(owner_client, [("KHR", "0")], end_date="2026-12-01")
    html = response.content.decode()
    assert "The end date must be on or after the start date." in html
    assert "Enter a rate above zero." in html
    assert not Trip.objects.exists()


def test_a_post_without_rate_rows_still_creates_the_trip(owner_client):
    response = owner_client.post(
        reverse("trip_create"),
        {
            "name": "Old form",
            "start_date": "2026-06-01",
            "end_date": "2026-06-05",
            "base_currency": "USD",
        },
    )
    assert response.status_code == 302
    trip = Trip.objects.get(name="Old form")
    assert (trip.start_date, trip.end_date) == (date(2026, 6, 1), date(2026, 6, 5))
    assert not trip.rates.exists()


def test_settings_rate_form_asks_for_suggestions(owner_client, trip):
    html = owner_client.get(reverse("trip_settings", args=[trip.id])).content.decode()
    assert f'data-rate-suggest="{reverse("rate_suggestion")}"' in html
    assert 'data-base="USD"' in html
    assert "js/date_range.js" in html and "js/trip_rates.js" in html
