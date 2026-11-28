"""English copies of text people write (docs/spec_languages.md section 3)."""

import csv
import io
import json
import re
from datetime import date

import pytest
from django.conf import settings as django_settings
from django.test import Client
from django.urls import reverse

from apps.disputes.models import Dispute, DisputeMessage
from apps.expenses import suggest
from apps.expenses.models import Category, Expense
from apps.trips import english, history
from apps.trips.models import Trip

pytestmark = pytest.mark.django_db

KHMER = "តាក់ស៊ីពីព្រលានយន្តហោះ"
KHMER_2 = "អាហារថ្ងៃត្រង់"
CHINESE = "机场出租车"


@pytest.fixture
def translator(settings, monkeypatch):
    """DeepSeek answers "EN: <text>"; ``calls`` lists every text it was asked to translate."""
    settings.DEEPSEEK_API_KEY = "test-key"
    calls = []

    def chat(messages, *, max_tokens, json_output=False):
        calls.append(messages[1]["content"])
        return f"EN: {messages[1]['content']}"

    monkeypatch.setattr(suggest, "chat", chat)
    return calls


def payload(trip, **extra):
    data = {
        "amount": "5",
        "currency": "USD",
        "category": trip.categories.get(name="Transport").id,
        "payer": trip.participants.first().id,
        "beneficiaries": [p.id for p in trip.participants.all()],
        "date": "2026-06-01",
        "description": "Taxi",
    }
    return {**data, **extra}


def add(client, trip, **extra):
    return client.post(reverse("expense_create", args=[trip.id]), payload(trip, **extra))


def test_detection_finds_khmer_and_han_letters_only():
    assert english.needs_copy(KHMER) and english.needs_copy(CHINESE)
    assert english.needs_copy("Taxi 机场") and english.needs_copy("㐀")  # Extension A.
    assert english.needs_copy("᧠")  # The Khmer symbols block.
    for text in ("Taxi to the airport", "Café ñ 2026 ฿ ₫", "", None, "Tuk-tuk 40,000 VND"):
        assert not english.needs_copy(text)


def test_english_text_gets_no_copy_and_no_request(owner_client, trip, translator):
    assert add(owner_client, trip).status_code == 302
    assert trip.expenses.get().description_en == ""
    assert translator == []


def test_khmer_text_gets_a_copy_made_on_save(owner_client, trip, translator):
    assert add(owner_client, trip, description=KHMER).status_code == 302
    expense = trip.expenses.get()
    assert expense.description == KHMER
    assert expense.description_en == f"EN: {KHMER}"
    assert translator == [KHMER]


def test_chinese_text_gets_a_copy_too(owner_client, trip, translator):
    add(owner_client, trip, description=CHINESE)
    assert trip.expenses.get().description_en == f"EN: {CHINESE}"


def test_an_english_version_the_person_wrote_is_kept_without_a_request(
    owner_client, trip, translator
):
    add(owner_client, trip, description=KHMER, description_en="Taxi from the airport")
    assert trip.expenses.get().description_en == "Taxi from the airport"
    assert translator == []


def test_a_failing_translator_returns_the_form_with_the_error(owner_client, trip, settings):
    settings.DEEPSEEK_API_KEY = "test-key"  # The key is set; the conftest blocks the network.
    response = add(owner_client, trip, description=KHMER)
    assert response.status_code == 200
    html = response.content.decode()
    assert "Write the English version." in html
    assert english_row(html) == ""  # The English box is open, for the person to fill.
    assert KHMER in html  # What was typed is kept.
    assert not trip.expenses.exists()


def test_no_key_means_the_person_writes_the_english(owner_client, trip, settings):
    settings.DEEPSEEK_API_KEY = ""
    response = add(owner_client, trip, description=KHMER)
    assert response.status_code == 200
    assert "Write the English version." in response.content.decode()


def test_the_daily_limit_returns_the_same_error(owner_client, trip, translator, settings):
    settings.DEEPSEEK_DAILY_LIMIT = 0
    response = add(owner_client, trip, description=KHMER)
    assert "Write the English version." in response.content.decode()
    assert translator == []


def english_row(html: str) -> str:
    """ " hidden" or "": whether the description's English box is hidden in the page."""
    found = re.search(
        r'<div class="field english-row" data-english-row( hidden)?>\s*<label for="id_description_en"',
        html,
    )
    assert found, "the description has an English box"
    return found.group(1) or ""


def test_the_english_box_shows_with_the_form_when_the_text_has_khmer(owner_client, trip):
    html = owner_client.get(reverse("expense_create", args=[trip.id])).content.decode()
    assert english_row(html) == " hidden"  # Hidden until the text has such letters.
    expense = Expense.objects.create(
        trip=trip, payer=trip.participants.first(), amount=1, currency="USD",
        date=date(2026, 6, 1), description=KHMER, description_en="Taxi",
        category=trip.categories.first(),
    )  # fmt: skip
    html = owner_client.get(reverse("expense_edit", args=[trip.id, expense.id])).content.decode()
    assert english_row(html) == ""
    assert "Taxi</textarea>" in html


def edit(client, trip, expense, **extra):
    data = payload(trip, **extra)
    return client.post(reverse("expense_edit", args=[trip.id, expense.id]), data)


def test_a_changed_original_makes_a_new_copy_unless_the_english_was_changed(
    owner_client, trip, translator
):
    add(owner_client, trip, description=KHMER)
    expense = trip.expenses.get()
    old_copy = expense.description_en
    # The original changes and the English box still holds the old copy: a new copy.
    edit(owner_client, trip, expense, description=KHMER_2, description_en=old_copy)
    expense.refresh_from_db()
    assert expense.description_en == f"EN: {KHMER_2}"
    # The original changes and the person changed the English: theirs is kept.
    edit(owner_client, trip, expense, description=KHMER, description_en="My own words")
    expense.refresh_from_db()
    assert expense.description_en == "My own words"
    # Nothing changes: no request, the stored copy stays.
    calls = len(translator)
    edit(owner_client, trip, expense, description=KHMER, description_en="My own words")
    assert len(translator) == calls
    # The original becomes English: the copy is cleared.
    edit(owner_client, trip, expense, description="Taxi", description_en="My own words")
    expense.refresh_from_db()
    assert expense.description_en == ""


def test_english_readers_see_the_copy_and_others_see_the_original(
    owner_client, trip, translator, settings
):
    add(owner_client, trip, description=KHMER)
    url = reverse("trip", args=[trip.id])
    assert f"EN: {KHMER}" in owner_client.get(url).content.decode()
    settings.LANGUAGE_CODE = "km"
    owner_client.cookies[django_settings.LANGUAGE_COOKIE_NAME] = "km"
    html = owner_client.get(url).content.decode()
    assert KHMER in html and "EN: " not in html
    owner_client.cookies[django_settings.LANGUAGE_COOKIE_NAME] = "zh-hans"
    assert "EN: " not in owner_client.get(url).content.decode()


def test_the_expense_page_title_and_the_deleted_page_use_the_copy_in_english(
    owner_client, trip, translator
):
    add(owner_client, trip, description=KHMER)
    expense = trip.expenses.get()
    owner_client.post(reverse("expense_delete", args=[trip.id, expense.id]))
    html = owner_client.get(reverse("expense_edit", args=[trip.id, expense.id])).content.decode()
    assert f"EN: {KHMER}" in html


def test_history_search_finds_the_english_copy_and_shows_it_in_english(
    owner_client, trip, translator
):
    add(owner_client, trip, description=KHMER)
    entry = trip.history.get()
    assert f"en: {KHMER}".lower() in entry.search_text
    page = owner_client.get(reverse("history", args=[trip.id]), {"q": "EN:"}).content.decode()
    assert f"EN: {KHMER}" in page
    assert "Taxi" not in page  # The sentence uses the copy, not the original.
    assert history.describe(entry).startswith("Owner added “EN: ")


def test_history_search_finds_an_english_copy_that_was_edited(owner_client, trip, translator):
    add(owner_client, trip, description=KHMER)
    expense = trip.expenses.get()
    edit(owner_client, trip, expense, description=KHMER, description_en="airport cab")
    page = owner_client.get(reverse("history", args=[trip.id]), {"q": "airport cab"})
    assert page.content.decode().count("airport cab") >= 1


def test_exports_include_the_english_copy(owner_client, trip, translator):
    add(owner_client, trip, description=KHMER)
    text = owner_client.get(reverse("report_export", args=[trip.id, "csv"])).content.decode("utf-8")
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    assert rows[0][1] == "Description" and rows[0][-1] == "Description in English"
    assert rows[1][1] == KHMER and rows[1][-1] == f"EN: {KHMER}"


def test_the_expense_search_finds_the_english_copy(owner_client, trip, translator):
    add(owner_client, trip, description=KHMER)
    page = owner_client.get(reverse("trip", args=[trip.id]), {"q": "en:"}).content.decode()
    assert f"EN: {KHMER}" in page


def test_the_suggestion_endpoint_fills_the_english_box(owner_client, translator):
    url = reverse("english_suggestion")
    assert owner_client.post(url, {"text": KHMER}).json() == {"english": f"EN: {KHMER}"}
    assert owner_client.post(url, {"text": "Taxi"}).json() == {"english": ""}
    assert translator == [KHMER]  # English text never reaches DeepSeek.


def test_the_suggestion_endpoint_needs_a_login(translator):
    response = Client().post(reverse("english_suggestion"), {"text": KHMER})
    assert response.status_code == 302 and translator == []


def test_the_suggestion_endpoint_is_limited(owner_client, translator, settings):
    settings.DEEPSEEK_DAILY_LIMIT = 0
    response = owner_client.post(reverse("english_suggestion"), {"text": KHMER})
    assert response.status_code == 429 and response.json() == {"english": ""}


def test_the_prompt_asks_for_a_short_natural_translation_keeping_names_and_numbers(
    owner_client, settings, monkeypatch
):
    settings.DEEPSEEK_API_KEY = "test-key"
    seen = []

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake(request, timeout):
        seen.append(json.loads(request.data))
        return Reply(json.dumps({"choices": [{"message": {"content": '"Taxi"'}}]}).encode())

    monkeypatch.setattr(suggest.urllib.request, "urlopen", fake)
    assert english.translate(KHMER, owner_client.session.get("_auth_user_id", 1)) == "Taxi"
    system = seen[0]["messages"][0]["content"]
    for word in ("short", "natural", "name", "number", "currency", "only"):
        assert word in system
    assert seen[0]["messages"][1]["content"] == KHMER


def test_trip_names_get_a_copy_and_show_it_in_english(owner_client, owner, translator):
    response = owner_client.post(
        reverse("trip_create"), {"name": KHMER, "country": "", "base_currency": "USD"}
    )
    assert response.status_code == 302
    trip = Trip.objects.get(created_by=owner)
    assert trip.name == KHMER and trip.name_en == f"EN: {KHMER}"
    assert f"EN: {KHMER}" in owner_client.get(reverse("home")).content.decode()


def test_a_trip_name_without_a_copy_returns_the_form_with_the_error(owner_client, settings):
    settings.DEEPSEEK_API_KEY = ""
    response = owner_client.post(
        reverse("trip_create"), {"name": KHMER, "country": "", "base_currency": "USD"}
    )
    assert response.status_code == 200
    assert "Write the English version." in response.content.decode()
    assert not Trip.objects.exists()


def test_custom_types_get_a_copy_and_the_json_says_when_the_english_is_needed(
    owner_client, trip, translator, settings
):
    url = reverse("category_create", args=[trip.id])
    response = owner_client.post(url, {"name": KHMER, "emoji": "🍜"})
    assert response.status_code == 201
    made = Category.objects.get(trip=trip, name=KHMER)
    assert made.name_en == f"EN: {KHMER}"
    assert response.json()["label"] == f"EN: {KHMER}"
    settings.DEEPSEEK_API_KEY = ""
    response = owner_client.post(url, {"name": KHMER_2, "emoji": "🍜"})
    assert response.status_code == 400
    assert response.json() == {"error": "Write the English version.", "english": True}


def test_default_types_are_not_translated_by_deepseek(owner_client, trip, translator):
    assert not any(english.needs_copy(c.name) for c in trip.categories.all())
    assert translator == []


def open_dispute(client, trip, expense, **data):
    return client.post(reverse("dispute_open", args=[trip.id, expense.id]), data, follow=True)


@pytest.fixture
def friends_expense(trip, make_user):
    from apps.trips.models import TripMember

    friend = make_user("friend")
    TripMember.objects.create(trip=trip, user=friend, role=TripMember.Role.MEMBER)
    person = trip.participants.get(name="Friend")
    person.user = friend
    person.save()
    expense = Expense.objects.create(
        trip=trip, payer=trip.participants.get(name="Owner"), amount=5, currency="USD",
        date=date(2026, 6, 1), description="Dinner", category=trip.categories.first(),
    )  # fmt: skip
    expense.beneficiaries.set(trip.participants.all())
    return friend, expense


def test_dispute_text_gets_a_copy_and_the_english_reader_sees_it(trip, friends_expense, translator):
    friend, expense = friends_expense
    client = Client()
    client.force_login(friend)
    response = open_dispute(client, trip, expense, reason=KHMER)
    dispute = Dispute.objects.get()
    assert dispute.reason == KHMER and dispute.reason_en == f"EN: {KHMER}"
    assert f"EN: {KHMER}" in response.content.decode()
    client.post(reverse("dispute_write", args=[trip.id, dispute.id]), {"text": CHINESE})
    assert DisputeMessage.objects.get().text_en == f"EN: {CHINESE}"
    entry = trip.history.filter(object_type="dispute", action="opened").get()
    assert f"EN: {KHMER}" in history.describe(entry)


def test_a_dispute_without_a_copy_comes_back_with_the_text_and_the_english_box(
    trip, friends_expense, settings
):
    settings.DEEPSEEK_API_KEY = ""
    friend, expense = friends_expense
    client = Client()
    client.force_login(friend)
    response = open_dispute(client, trip, expense, reason=KHMER)
    html = response.content.decode()
    assert not Dispute.objects.exists()
    assert "Write the English version." in html
    assert KHMER in html  # The typed text is kept in the form.
    # Writing the English version now saves.
    response = open_dispute(client, trip, expense, reason=KHMER, reason_en="I did not eat.")
    assert Dispute.objects.get().reason_en == "I did not eat."


def test_the_owner_closing_a_dispute_with_khmer_gets_a_copy(
    owner_client, trip, friends_expense, translator
):
    friend, expense = friends_expense
    client = Client()
    client.force_login(friend)
    open_dispute(client, trip, expense, reason="Not mine")
    dispute = Dispute.objects.get()
    owner_client.post(reverse("dispute_close", args=[trip.id, dispute.id]), {"reason": KHMER})
    dispute.refresh_from_db()
    assert dispute.state == "closed" and dispute.close_reason_en == f"EN: {KHMER}"
