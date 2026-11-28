import pytest
from django.contrib.auth import get_user_model

from apps.trips.models import Participant, Trip, TripMember

PASSWORD = "a-long-test-password-42"


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
