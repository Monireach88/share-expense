from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

from apps.trips.models import Participant, Trip, TripMember

PASSWORD = "a-long-test-password-42"
LOCALE_DIR = Path(__file__).resolve().parent.parent / "locale"


def compile_messages(locale_dir: Path) -> int:
    """Compile every locale/<code>/LC_MESSAGES/django.po into a .mo file when the .mo is missing
    or older than the .po (the host has no gettext tools; polib does the same job). Returns how
    many files were compiled. The .mo files are never committed (.gitignore)."""
    import polib

    count = 0
    for po_path in sorted(locale_dir.glob("*/LC_MESSAGES/django.po")):
        mo_path = po_path.with_suffix(".mo")
        if mo_path.exists() and mo_path.stat().st_mtime >= po_path.stat().st_mtime:
            continue
        polib.pofile(str(po_path)).save_as_mofile(str(mo_path))
        count += 1
    return count


def pytest_configure(config):
    compile_messages(LOCALE_DIR)


@pytest.fixture
def make_user(db):
    def make(username="owner", **extra):
        extra.setdefault("first_name", username.title())
        return get_user_model().objects.create_user(username=username, password=PASSWORD, **extra)

    return make


@pytest.fixture
def make_trip(db):
    def make(owner, name="Saigon check-up", people=("Owner", "Friend"), **extra):
        trip = Trip.objects.create(name=name, created_by=owner, **extra)
        TripMember.objects.create(trip=trip, user=owner, role=TripMember.Role.OWNER)
        for person in people:
            Participant.objects.create(
                trip=trip, name=person, user=owner if person == "Owner" else None
            )
        return trip

    return make


@pytest.fixture
def owner(make_user):
    return make_user("owner")


@pytest.fixture
def trip(make_trip, owner):
    return make_trip(owner)


@pytest.fixture
def owner_client(client, owner):
    client.force_login(owner)
    return client


@pytest.fixture(autouse=True)
def no_dns(request, monkeypatch):
    """Tests never ask real DNS: every invite domain receives email, unless a test opts out
    with the "real_email_check" marker and mocks the resolver itself."""
    if "real_email_check" in request.keywords:
        return
    from apps.trips import email_check

    monkeypatch.setattr(email_check, "receives_email", lambda domain: True)


@pytest.fixture(autouse=True)
def no_exchange_rates(monkeypatch):
    """Tests never call the exchange rate service: the call fails unless a test replaces it."""
    from apps.trips import rates

    def offline(request, timeout):
        raise OSError("tests do not call the exchange rate service")

    monkeypatch.setattr(rates, "urlopen", offline)


@pytest.fixture(autouse=True)
def english_by_default(settings):
    """The site starts in Khmer, but most tests read English text. A test that needs another
    language sets settings.LANGUAGE_CODE itself or sends the language cookie."""
    settings.LANGUAGE_CODE = "en"


@pytest.fixture(autouse=True)
def no_translator(monkeypatch):
    """Tests never call DeepSeek, which also writes the English copies: the call fails unless a
    test replaces it (tests/test_english_copy.py does)."""
    import types
    import urllib.error
    import urllib.request

    from apps.expenses import suggest

    def offline(request, timeout):
        raise urllib.error.URLError("tests do not call DeepSeek")

    # A private copy of the module for suggest.py only, so no other code is affected.
    blocked = types.SimpleNamespace(
        request=types.SimpleNamespace(Request=urllib.request.Request, urlopen=offline),
        error=urllib.error,
    )
    monkeypatch.setattr(suggest, "urllib", blocked)
