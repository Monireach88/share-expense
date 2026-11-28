"""Usernames (spec section 6.1). Invites, Google sign-in and closing an account are in
``test_invites``."""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client
from django.urls import reverse

from .conftest import PASSWORD
from .test_google import google  # noqa: F401
from .test_invites import accept_with_google, invite_link
from .test_roles import Crew

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def crew(db):
    return Crew()


@pytest.fixture
def admin_client(make_user):
    client = Client()
    client.force_login(make_user("boss", is_staff=True, is_superuser=True))
    return client


def admin_add(client, username):
    """The admin's "add user" form: since section 6.4 the only other way to make an account."""
    return client.post(
        reverse("admin:accounts_user_add"),
        {
            "username": username,
            "password1": PASSWORD,
            "password2": PASSWORD,
            "usable_password": "true",
        },
    )


def google_signup(crew, google, email):  # noqa: F811
    """A new person accepts a personal invite with Google; returns the new account."""
    accept_with_google(Client(), invite_link(crew, email), google, email)
    return User.objects.get(email__iexact=email)


# --- 6.1 Usernames ------------------------------------------------------------------------------


def test_username_case_does_not_create_a_second_account(admin_client, make_user):
    make_user("maly")
    response = admin_add(admin_client, "Maly")
    assert "This username is taken." in response.content.decode()
    assert User.objects.filter(username__iexact="maly").count() == 1


@pytest.mark.parametrize("bad", ["ma.ly", "ab", "x" * 31, "ma ly", "mály", "a-b-c"])
def test_invalid_username_characters_or_length_are_refused(admin_client, bad):
    response = admin_add(admin_client, bad)
    assert "Use only the characters listed above." in response.content.decode()
    assert User.objects.count() == 1


def test_the_admin_stores_the_username_in_lowercase(admin_client):
    assert admin_add(admin_client, "New_Girl_30").status_code == 302
    assert User.objects.filter(username="new_girl_30").exists()
    assert admin_add(admin_client, "A" * 30).status_code == 302
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


def test_a_google_account_gets_a_username_from_its_email_name(crew, google):  # noqa: F811
    assert google_signup(crew, google, "Gina.Sok+x@Example.com").username == "ginasokx"


def test_a_google_username_gets_a_number_when_taken(crew, google):  # noqa: F811
    assert google_signup(crew, google, "Sam@other.example").username == "sam2"


def test_a_google_email_name_that_is_too_short_or_foreign_still_gives_a_valid_name(
    crew,
    google,  # noqa: F811
):
    google["given_name"] = "Gina"
    assert google_signup(crew, google, "x@example.com").username == "gina"


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
