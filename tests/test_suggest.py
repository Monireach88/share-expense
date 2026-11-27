import io
import json
from datetime import date

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.expenses import suggest
from apps.expenses.models import Expense


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def deepseek(settings, monkeypatch):
    """Replace the DeepSeek call: record each request and answer with ``reply["text"]``."""
    settings.DEEPSEEK_API_KEY = "test-key"
    sent, reply = [], {"text": "Tuk-tuk from the airport to the hotel"}

    def fake_urlopen(request, timeout):
        sent.append(json.loads(request.data))
        answer = {"choices": [{"message": {"content": reply["text"]}}]}
        return FakeResponse(json.dumps(answer).encode())

    monkeypatch.setattr(suggest.urllib.request, "urlopen", fake_urlopen)
    return sent, reply


def ask(client, trip, text):
    return client.post(reverse("description_suggestion", args=[trip.id]), {"text": text})


def test_suggestion_uses_the_trips_descriptions_as_style(owner_client, trip, deepseek):
    sent, _reply = deepseek
    owner_p = trip.participants.first()
    expense = Expense.objects.create(
        trip=trip, payer=owner_p, amount=1, currency="USD", date=date(2026, 6, 1),
        description="Breakfast noodles", category=trip.categories.first(),
    )  # fmt: skip
    expense.beneficiaries.set([owner_p])
    response = ask(owner_client, trip, "tuktuk from airport to hotell")
    assert response.json() == {"suggestion": "Tuk-tuk from the airport to the hotel"}
    prompt = sent[0]["messages"][1]["content"]
    assert "- Breakfast noodles" in prompt and "tuktuk from airport to hotell" in prompt
    assert sent[0]["model"] == "deepseek-flash"


def test_no_suggestion_when_the_text_is_already_fine(owner_client, trip, deepseek):
    _sent, reply = deepseek
    reply["text"] = '"Hotel night."'
    assert ask(owner_client, trip, "Hotel night").json() == {"suggestion": ""}


def test_no_key_means_no_suggestions_and_no_request(owner_client, trip, settings, monkeypatch):
    settings.DEEPSEEK_API_KEY = ""
    monkeypatch.setattr(suggest.urllib.request, "urlopen", lambda *a, **k: pytest.fail("called"))
    assert ask(owner_client, trip, "tuktuk").json() == {"suggestion": ""}
    page = owner_client.get(reverse("expense_create", args=[trip.id])).content.decode()
    assert "data-suggest" not in page


def test_a_failing_service_gives_no_suggestion(owner_client, trip, settings, monkeypatch):
    settings.DEEPSEEK_API_KEY = "test-key"

    def broken(*args, **kwargs):
        raise suggest.urllib.error.URLError("down")

    monkeypatch.setattr(suggest.urllib.request, "urlopen", broken)
    assert ask(owner_client, trip, "tuktuk").json() == {"suggestion": ""}


def test_suggestions_are_limited_per_account(owner_client, trip, deepseek, monkeypatch):
    monkeypatch.setattr(suggest, "LIMIT", 2)
    from django.core.cache import cache

    cache.clear()
    assert ask(owner_client, trip, "one a").status_code == 200
    assert ask(owner_client, trip, "two b").status_code == 200
    assert ask(owner_client, trip, "three c").status_code == 429


def test_outsiders_get_no_suggestions(client, trip, make_user, deepseek):
    client.force_login(make_user("stranger"))
    assert ask(client, trip, "tuktuk").status_code == 404


@pytest.fixture
def ai_reply(settings, monkeypatch):
    """Fake DeepSeek for "Add with AI": answer with ``reply`` as JSON, record each prompt."""
    settings.DEEPSEEK_API_KEY = "test-key"
    sent, reply = [], {}

    def fake_chat(messages, *, max_tokens, json_output=False):
        sent.append(messages)
        return json.dumps(reply)

    monkeypatch.setattr(suggest, "chat", fake_chat)
    return sent, reply


def fill(client, trip, text):
    return client.post(reverse("expense_ai_fill", args=[trip.id]), {"text": text}).json()


def test_ai_fills_only_what_the_sentence_states(owner_client, trip, ai_reply):
    from apps.trips.models import ExchangeRate

    ExchangeRate.objects.create(trip=trip, currency="VND", rate=25000)
    owner_p, friend = trip.participants.all()
    _sent, reply = ai_reply
    reply.update(
        is_expense=True, amount="40,000", currency="VND", payer="owner",
        beneficiaries=["Owner", "friend"], everyone=False, type="Food & drink",
        description="Drinks", date="2026-11-25",
    )  # fmt: skip
    data = fill(owner_client, trip, "Owner bought drinks for Owner and Friend, 40000 VND, Nov 25")
    fields = data["fields"]
    assert data["missing"] == []
    assert fields["amount"] == "40000" and fields["currency"] == "VND"
    assert fields["payer"] == str(owner_p.id)
    assert fields["beneficiaries"] == [str(owner_p.id), str(friend.id)]
    assert fields["category"] == str(trip.categories.get(name="Food & drink").pk)
    assert fields["description"] == "Drinks" and fields["date"] == "2026-11-25"


def test_ai_reports_what_is_missing_and_never_guesses(owner_client, trip, ai_reply):
    _sent, reply = ai_reply
    reply.update(is_expense=True, amount="12", currency="THB", payer="Bob", beneficiaries=[],
                 everyone=False, type=None, description=None, date=None)  # fmt: skip
    data = fill(owner_client, trip, "Bob paid 12 baht")
    fields, missing = data["fields"], data["missing"]
    assert "payer" not in fields and "beneficiaries" not in fields and "currency" not in fields
    assert any("“Bob”" in m for m in missing)  # No traveler is called Bob.
    assert any("THB has no exchange rate" in m for m in missing)
    assert "who it was for" in missing and "the type" in missing and "what was bought" in missing
    assert fields["date"] == timezone.localdate().isoformat()  # No date given: today.


def test_ai_matches_a_short_name_only_when_one_traveler_fits(trip):
    from apps.expenses.ai_fill import match_traveler
    from apps.trips.models import Participant

    a = Participant.objects.create(trip=trip, name="HENG MALY")
    Participant.objects.create(trip=trip, name="HENG SOPHORN")
    travelers = list(trip.participants.all())
    assert match_traveler("Maly", travelers) == a
    assert match_traveler("heng maly", travelers) == a
    assert match_traveler("Heng", travelers) is None  # Two travelers fit: no guess.


def test_ai_refuses_text_that_is_not_an_expense(owner_client, trip, ai_reply):
    _sent, reply = ai_reply
    reply.update(is_expense=False)
    assert fill(owner_client, trip, "Write me a poem about Hanoi")["error"] == (
        "This box only adds expenses."
    )


def test_everyone_and_me_are_understood(owner_client, trip, ai_reply):
    sent, reply = ai_reply
    owner_p, friend = trip.participants.all()
    reply.update(is_expense=True, amount="9", currency="USD", payer="Owner", beneficiaries=[],
                 everyone=True, type="Transport", description="Taxi", date=None)  # fmt: skip
    data = fill(owner_client, trip, "I paid 9 USD for a taxi for everyone")
    assert data["fields"]["beneficiaries"] == [str(owner_p.id), str(friend.id)]
    assert '"I" or "me" means Owner' in sent[0][0]["content"]
