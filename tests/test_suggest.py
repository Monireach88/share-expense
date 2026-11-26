import io
import json
from datetime import date

import pytest
from django.urls import reverse

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
