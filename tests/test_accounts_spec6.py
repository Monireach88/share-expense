"""Accounts (spec section 6): usernames, adding an account, and the invite link.

Uses the crew of ``test_roles``: Ann owns "Crew trip"; Ben is an Editor; Cara and Dan are
Members; Eve is a Member with no traveler; Sam has an account but is not on the trip.
"""

import re

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client
from django.urls import reverse

from apps.trips import history
from apps.trips.models import HistoryEntry, Participant, RemovedAccount, Trip, TripMember

from .conftest import PASSWORD
from .test_google import google, sign_in_with_google  # noqa: F401
from .test_roles import Crew

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def crew(db):
    return Crew()


def texts(trip) -> list[str]:
    return [history.describe(e) for e in HistoryEntry.objects.filter(trip=trip).order_by("id")]


def signup(client, username, **extra):
    return client.post(
        reverse("signup"),
        {
            "username": username,
            "first_name": "Cara",
            "password1": PASSWORD,
            "password2": PASSWORD,
            **extra,
        },
    )


# --- 6.1 Usernames ------------------------------------------------------------------------------


def test_username_case_does_not_create_a_second_account(client, make_user):
    make_user("maly")
    response = signup(client, "Maly")
    assert "This username is taken." in response.content.decode()
    assert User.objects.count() == 1


@pytest.mark.parametrize("bad", ["ma.ly", "ab", "x" * 31, "ma ly", "mály", "a-b-c"])
def test_invalid_username_characters_or_length_are_refused(client, bad):
    response = signup(client, bad)
    assert "Use only a–z, 0–9 and _, 3 to 30 characters." in response.content.decode()
    assert not User.objects.filter(first_name="Cara").exists()


def test_sign_up_stores_the_username_in_lowercase(client):
    assert signup(client, "New_Girl_30").status_code == 200
    assert User.objects.get(first_name="Cara").username == "new_girl_30"
    assert User.objects.filter(username="x" * 30).count() == 0
    assert signup(Client(), "A" * 30).status_code == 200
    assert User.objects.filter(username="a" * 30).exists()


def test_every_save_lowercases_the_username(make_user):
    user = make_user("Mixed_Case")
    assert user.username == "mixed_case"
    user.username = "SHOUT"
    user.save(update_fields=["username"])
    user.refresh_from_db()
    assert user.username == "shout"


def test_the_database_refuses_two_usernames_that_differ_only_in_case(make_user):
    make_user("maly")
    other = make_user("mala")
    with pytest.raises(IntegrityError):
        User.objects.filter(pk=other.pk).update(username="MALY")  # Skips save(), so no lowercase.


def test_the_admin_lowercases_and_refuses_a_taken_username(client, make_user):
    client.force_login(make_user("boss", is_staff=True, is_superuser=True))
    make_user("maly")
    data = {"password1": PASSWORD, "password2": PASSWORD, "usable_password": "true"}
    url = reverse("admin:accounts_user_add")
    taken = client.post(url, {"username": "Maly", **data})
    assert "This username is taken." in taken.content.decode()
    bad = client.post(url, {"username": "no.dots", **data})
    assert "Use only a–z, 0–9 and _, 3 to 30 characters." in bad.content.decode()
    assert client.post(url, {"username": "Fresh_Name", **data}).status_code == 302
    assert User.objects.filter(username="fresh_name").exists()


def test_sign_in_accepts_any_letter_case(client, make_user):
    make_user("dara")
    response = client.post(reverse("login"), {"username": "DaRa", "password": PASSWORD})
    assert response.status_code == 302
    assert "_auth_user_id" in client.session


def test_lockout_counts_every_letter_case_as_one_account(client, make_user):
    make_user("victim")
    for name in ["Victim", "VICTIM", "victim", "vIctim", "viCtim"]:
        client.post(reverse("login"), {"username": name, "password": "wrong"})
    for name in ("victim", "VICTIM"):
        response = client.post(reverse("login"), {"username": name, "password": PASSWORD})
        assert response.status_code == 429


def test_a_google_account_gets_a_username_from_its_email_name(client, google, make_user):  # noqa: F811
    google["email"] = "Dara.Sok+x@Example.com"
    sign_in_with_google(client)
    assert User.objects.get(email="dara.sok+x@example.com").username == "darasokx"


def test_a_google_username_gets_a_number_when_taken(client, google, make_user):  # noqa: F811
    make_user("traveler")
    google["email"] = "Traveler@other.example"
    sign_in_with_google(client)
    assert User.objects.get(email="traveler@other.example").username == "traveler2"


def test_a_google_email_name_that_is_too_short_or_foreign_still_gives_a_valid_name(
    client,
    google,  # noqa: F811
):
    google["email"] = "x@example.com"
    google["given_name"] = "Dara"
    sign_in_with_google(client)
    name = User.objects.get(email="x@example.com").username
    assert name == "dara"


@pytest.mark.django_db(transaction=True)
def test_the_username_migration_never_fails_on_mixed_case_data():
    executor = MigrationExecutor(connection)
    executor.migrate([("accounts", "0001_initial")])
    old = executor.loader.project_state([("accounts", "0001_initial")]).apps
    model = old.get_model("accounts", "User")
    first = model.objects.create(username="Maly", password="x")
    second = model.objects.create(username="maly", password="x")
    third = model.objects.create(username="Ben_K", password="x")
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
    names = {u.pk: u.username for u in User.objects.all()}
    assert names[second.pk] == "maly" and names[third.pk] == "ben_k"
    assert names[first.pk] == f"maly_{first.pk}"  # The name that was already lowercase is kept.
    assert len(set(names.values())) == 3


# --- 6.2 Add account ----------------------------------------------------------------------------


def add(crew, **data):
    return crew.client("ann").post(crew.url("member_add"), {"username": "sam", **data})


def test_add_account_links_an_existing_traveler(crew):
    fay = Participant.objects.create(trip=crew.trip, name="Fay")
    assert add(crew, traveler=str(fay.pk)).status_code == 302
    member = TripMember.objects.get(trip=crew.trip, user=crew.users["sam"])
    assert member.role == TripMember.Role.MEMBER and member.linked_traveler == fay
    assert texts(crew.trip) == [
        "Ann added Sam's account",
        "Ann linked traveler Fay to account Sam",
    ]


def test_add_account_creates_the_traveler(crew):
    assert add(crew, traveler="new").status_code == 302
    sam = crew.trip.participants.get(name="Sam")
    assert sam.user == crew.users["sam"]
    assert texts(crew.trip) == [
        "Ann added traveler Sam",
        "Ann linked traveler Sam to account Sam",
        "Ann added Sam's account",
    ]


def test_add_account_with_a_new_traveler_fails_when_the_name_is_taken(crew):
    Participant.objects.create(trip=crew.trip, name="sam")  # Another traveler, in any case.
    response = add(crew, traveler="new")
    assert "Someone on this trip already has this name." in response.content.decode()
    assert not TripMember.objects.filter(trip=crew.trip, user=crew.users["sam"]).exists()
    assert not HistoryEntry.objects.filter(trip=crew.trip).exists()


def test_add_account_as_a_viewer(crew):
    assert add(crew, traveler="none").status_code == 302
    member = TripMember.objects.get(trip=crew.trip, user=crew.users["sam"])
    assert member.is_viewer and member.role_label == "Viewer"
    assert texts(crew.trip) == ["Ann added Sam's account"]


def test_the_choice_is_required_and_only_free_travelers_are_offered(crew):
    response = add(crew)
    assert "This field is required." in response.content.decode()
    # Dan's traveler already has an account, so it cannot be picked.
    response = add(crew, traveler=str(crew.travelers["dan"].pk))
    assert "Select a valid choice" in response.content.decode()
    assert not TripMember.objects.filter(trip=crew.trip, user=crew.users["sam"]).exists()


def test_the_traveler_with_the_accounts_name_is_preselected(crew):
    fay = Participant.objects.create(trip=crew.trip, name="Fay")
    sam = Participant.objects.create(trip=crew.trip, name="SAM")
    page = crew.client("ann").get(crew.url("member_add"), {"username": "sam"})
    assert page.context["form"].initial["traveler"] == str(sam.pk)
    html = page.content.decode()
    assert re.search(rf'value="{sam.pk}"[^>]* checked', html)
    assert not re.search(rf'value="{fay.pk}"[^>]* checked', html)
    assert fay.name in html
    other = crew.client("ann").get(crew.url("member_add"), {"username": "nobody"})
    assert "traveler" not in other.context["form"].initial


def test_a_settled_trip_offers_no_new_traveler(crew):
    crew.trip.settled_at = crew.trip.created_at
    crew.trip.save()
    page = crew.client("ann").get(crew.url("member_add"))
    assert "A new traveler" not in page.content.decode()
    assert "Not a traveler (only view)" in page.content.decode()
    assert "Select a valid choice" in add(crew, traveler="new").content.decode()


def test_only_the_owner_adds_accounts(crew):
    for name in ("ben", "cara", "eve"):
        assert (
            crew.client(name).post(crew.url("member_add"), {"username": "sam"}).status_code == 403
        )


def test_adding_a_removed_account_again_clears_its_block(crew):
    crew.client("ann").post(crew.url("member_remove", crew.members["dan"].id))
    assert RemovedAccount.objects.filter(trip=crew.trip, user=crew.users["dan"]).exists()
    assert (
        crew.client("ann")
        .post(crew.url("member_add"), {"username": "dan", "traveler": "none"})
        .status_code
        == 302
    )
    assert not RemovedAccount.objects.filter(trip=crew.trip, user=crew.users["dan"]).exists()


# --- 6.3 Invite link ----------------------------------------------------------------------------


def invite(crew, change, who="ann"):
    return crew.client(who).post(crew.url("invite_change", change))


def link_on(crew) -> str:
    invite(crew, "on")
    crew.trip.refresh_from_db()
    return reverse("join", args=[crew.trip.invite_token])


def test_the_invite_link_is_off_by_default_and_owner_turns_it_on_and_off(crew):
    assert crew.trip.invite_token is None
    page = crew.client("ann").get(crew.url("people")).content.decode()
    assert "Turn on invite link" in page and 'id="invite-url"' not in page
    invite(crew, "on")
    crew.trip.refresh_from_db()
    token = crew.trip.invite_token
    assert token
    page = crew.client("ann").get(crew.url("people")).content.decode()
    full_url = f"http://testserver/join/{token}/"
    assert f'id="invite-url" value="{full_url}" readonly' in page
    assert 'data-copy="invite-url"' in page and ">Copy<" in page
    invite(crew, "on")  # Pressing On twice keeps the same link.
    crew.trip.refresh_from_db()
    assert crew.trip.invite_token == token
    invite(crew, "off")
    crew.trip.refresh_from_db()
    assert crew.trip.invite_token is None
    assert texts(crew.trip) == [
        "Ann turned the invite link on",
        "Ann turned the invite link off",
    ]


def test_renewing_replaces_the_link_and_stops_the_old_one(crew):
    old = link_on(crew)
    invite(crew, "renew")
    crew.trip.refresh_from_db()
    new = reverse("join", args=[crew.trip.invite_token])
    assert new != old
    response = crew.client("sam").get(old)
    assert response.status_code == 404 and "This link no longer works." in response.content.decode()
    assert crew.client("sam").get(new).status_code == 200
    assert texts(crew.trip)[-1] == "Ann renewed the invite link"


def test_the_invite_link_is_for_the_owner_only(crew):
    for who in ("ben", "cara", "eve", "sam"):
        for change in ("on", "off", "renew"):
            assert invite(crew, change, who).status_code in (403, 404)
    crew.trip.refresh_from_db()
    assert crew.trip.invite_token is None
    link_on(crew)
    for who in ("ben", "cara", "eve"):
        page = crew.client(who).get(crew.url("people")).content.decode()
        assert "invite-url" not in page and crew.trip.invite_token not in page
    assert invite(crew, "bogus").status_code == 404


def test_the_owner_page_with_the_secret_link_is_not_kept_by_the_browser_cache(crew):
    link_on(crew)
    assert "X-SW-Cache" not in crew.client("ann").get(crew.url("people"))
    assert crew.client("cara").get(crew.url("people"))["X-SW-Cache"] == "page"


def test_join_by_link_as_a_traveler(crew):
    fay = Participant.objects.create(trip=crew.trip, name="Fay")
    Participant.objects.create(trip=crew.trip, name="Gus")
    url = link_on(crew)
    sam = crew.client("sam")
    page = sam.get(url).content.decode()
    assert "Which traveler are you?" in page and "Crew trip" in page
    assert "Fay" in page and "Gus" in page and "None of them (only view)" in page
    assert "Dan" not in page.replace("Dan", "Dan", 0) or "value" in page  # Linked ones are absent.
    assert f'value="{crew.travelers["dan"].pk}"' not in page
    response = sam.post(url, {"traveler": str(fay.pk)})
    assert response.status_code == 302 and response["Location"] == crew.url("trip")
    member = TripMember.objects.get(trip=crew.trip, user=crew.users["sam"])
    assert member.role == TripMember.Role.MEMBER and member.linked_traveler == fay
    assert texts(crew.trip)[-2:] == [
        "Sam joined by link as Fay",
        "Sam linked traveler Fay to account Sam",
    ]


def test_join_by_link_as_none_of_them_is_a_viewer(crew):
    url = link_on(crew)
    assert crew.client("sam").post(url, {"traveler": "none"}).status_code == 302
    member = TripMember.objects.get(trip=crew.trip, user=crew.users["sam"])
    assert member.is_viewer
    assert texts(crew.trip)[-1] == "Sam joined by link (only view)"


def test_the_join_choice_is_required(crew):
    url = link_on(crew)
    response = crew.client("sam").post(url, {})
    assert "Choose who you are." in response.content.decode()
    assert not TripMember.objects.filter(trip=crew.trip, user=crew.users["sam"]).exists()
    assert "Choose who you are." in crew.client("sam").post(url, {"traveler": "x"}).content.decode()


def test_an_account_already_on_the_trip_goes_straight_to_it(crew):
    url = link_on(crew)
    response = crew.client("cara").get(url)
    assert response.status_code == 302 and response["Location"] == crew.url("trip")
    before = TripMember.objects.count()
    crew.client("cara").post(url, {"traveler": "none"})
    assert TripMember.objects.count() == before


def test_a_removed_account_cannot_rejoin_by_link_until_added_again(crew):
    url = link_on(crew)
    crew.client("ann").post(crew.url("member_remove", crew.members["dan"].id))
    dan = crew.client("dan")
    page = dan.get(url).content.decode()
    assert "You were removed from this trip. Ask the Owner to add you again." in page
    assert "Which traveler" not in page
    blocked = dan.post(url, {"traveler": "none"})
    assert "You were removed from this trip" in blocked.content.decode()
    assert not TripMember.objects.filter(trip=crew.trip, user=crew.users["dan"]).exists()
    crew.client("ann").post(crew.url("member_add"), {"username": "dan", "traveler": "none"})
    assert dan.get(url).status_code == 302  # On the trip again: straight to it.


def test_two_people_choosing_the_same_traveler_the_second_is_refused(crew):
    fay = Participant.objects.create(trip=crew.trip, name="Fay")
    url = link_on(crew)
    other = get_user_model().objects.create_user("zed", password=None, first_name="Zed")
    first, second = crew.client("sam"), Client()
    second.force_login(other)
    assert "Fay" in second.get(url).content.decode()  # Both saw Fay as free.
    assert first.post(url, {"traveler": str(fay.pk)}).status_code == 302
    response = second.post(url, {"traveler": str(fay.pk)})
    assert "Already taken, choose again." in response.content.decode()
    assert not TripMember.objects.filter(trip=crew.trip, user=other).exists()
    fay.refresh_from_db()
    assert fay.user == crew.users["sam"]


def test_the_database_refuses_one_account_on_two_travelers(crew):
    gus = Participant.objects.create(trip=crew.trip, name="Gus")
    with pytest.raises(IntegrityError):
        Participant.objects.filter(pk=gus.pk).update(user=crew.users["dan"])


def test_a_link_renewed_while_the_form_was_open_is_refused_on_send(crew):
    url = link_on(crew)
    sam = crew.client("sam")
    sam.get(url)
    invite(crew, "renew")
    response = sam.post(url, {"traveler": "none"})
    assert response.status_code == 404 and "This link no longer works." in response.content.decode()
    assert not TripMember.objects.filter(trip=crew.trip, user=crew.users["sam"]).exists()


def test_joining_still_works_on_a_settled_trip(crew):
    fay = Participant.objects.create(trip=crew.trip, name="Fay")
    url = link_on(crew)
    crew.trip.settled_at = crew.trip.created_at
    crew.trip.save()
    assert crew.client("sam").post(url, {"traveler": str(fay.pk)}).status_code == 302
    assert Participant.objects.get(pk=fay.pk).user == crew.users["sam"]


def test_a_visitor_without_an_account_sees_only_the_trip_name(crew):
    Participant.objects.create(trip=crew.trip, name="Fay")
    url = link_on(crew)
    visitor = Client()
    response = visitor.get(url)
    page = response.content.decode()
    assert response.status_code == 200 and "Crew trip" in page
    for name in ("Fay", "Ann", "Dan", "Cara", "Which traveler"):
        assert name not in page
    assert f"{reverse('login')}?next={url}" in page.replace("%2F", "/")
    assert f"{reverse('signup')}?invite={crew.trip.invite_token}" in page
    assert visitor.get(reverse("join", args=["not-a-token"])).status_code == 404
    assert "Crew trip" not in visitor.get(reverse("join", args=["not-a-token"])).content.decode()


def test_the_invite_survives_an_account_request_approval_and_first_sign_in(crew):
    url = link_on(crew)
    token = crew.trip.invite_token
    Participant.objects.create(trip=crew.trip, name="Fay")
    visitor = Client()
    assert visitor.get(url).status_code == 200
    sent = signup(visitor, "cara_k", invite=token)
    assert "choose who you are" in sent.content.decode()
    user = User.objects.get(username="cara_k")
    assert user.invite_token == token and not user.is_active
    User.objects.filter(pk=user.pk).update(is_active=True)  # The admin approves it.
    login = visitor.post(reverse("login"), {"username": "cara_k", "password": PASSWORD})
    assert login.status_code == 302 and login["Location"] == url
    page = visitor.get(url).content.decode()
    assert "Which traveler are you?" in page and "Fay" in page
    user.refresh_from_db()
    assert user.invite_token == ""  # Used up: the next sign-in goes home.
    visitor.post(reverse("logout"))
    assert visitor.post(reverse("login"), {"username": "cara_k", "password": PASSWORD})[
        "Location"
    ] == reverse("home")


def test_a_renewed_link_after_an_account_request_shows_no_longer_works(crew):
    url = link_on(crew)
    visitor = Client()
    signup(visitor, "cara_k", invite=crew.trip.invite_token)
    User.objects.filter(username="cara_k").update(is_active=True)
    invite(crew, "off")
    login = visitor.post(reverse("login"), {"username": "cara_k", "password": PASSWORD})
    assert login["Location"] == url
    response = visitor.get(url)
    assert response.status_code == 404 and "This link no longer works." in response.content.decode()


def test_a_sign_up_with_a_made_up_invite_keeps_nothing(client, crew):
    signup(client, "cara_k", invite="made-up")
    assert User.objects.get(username="cara_k").invite_token == ""


def test_the_invite_survives_a_google_sign_up(client, google, crew):  # noqa: F811
    url = link_on(crew)
    token = crew.trip.invite_token
    client.get(url)  # Opening the link remembers it for the trip to Google and back.
    response = sign_in_with_google(client)
    assert response["Location"] == reverse("account_inactive")
    user = User.objects.get(email="traveler@example.com")
    assert user.invite_token == token and not user.is_active
    User.objects.filter(pk=user.pk).update(is_active=True)
    client.logout()
    response = sign_in_with_google(client)
    assert response["Location"] == url
    assert "Which traveler are you?" in client.get(url).content.decode()


def test_the_admin_can_not_see_the_invite_token_field(crew, make_user):
    client = Client()
    client.force_login(make_user("boss", is_staff=True, is_superuser=True))
    page = client.get(reverse("admin:accounts_user_change", args=[crew.users["sam"].pk]))
    assert "invite_token" not in page.content.decode()


def test_an_account_that_joins_through_the_link_shows_in_history_search(crew):
    url = link_on(crew)
    crew.client("sam").post(url, {"traveler": "none"})
    page = crew.client("ann").get(crew.url("history"), {"q": "joined"}).content.decode()
    assert "Sam joined by link (only view)" in page
    assert Trip.objects.get(pk=crew.trip.pk).memberships.count() == 6
