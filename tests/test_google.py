"""Google sign-in through the real URLs; only the two calls to Google's servers are faked."""

from urllib.parse import parse_qs, urlparse

import pytest
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

GOOGLE = {
    "google": {
        "APPS": [{"client_id": "test-client", "secret": "test-secret", "key": ""}],
        "SCOPE": ["profile", "email"],
    }
}


@pytest.fixture
def google(settings, monkeypatch):
    """Turn Google sign-in on and decide who Google says the visitor is."""
    settings.GOOGLE_CLIENT_ID = "test-client"
    settings.SOCIALACCOUNT_PROVIDERS = GOOGLE
    person = {
        "sub": "google-123",
        "email": "traveler@example.com",
        "email_verified": True,
        "name": "Dara Sok",
        "given_name": "Dara",
        "family_name": "Sok",
        "picture": "https://example.com/p.png",
    }
    monkeypatch.setattr(
        GoogleOAuth2Adapter,
        "get_access_token_data",
        lambda self, request, app, client, **kw: {"access_token": "t", "id_token": "i"},
    )
    monkeypatch.setattr(
        GoogleOAuth2Adapter, "_decode_id_token", lambda self, app, token: dict(person)
    )
    return person


def sign_in_with_google(client, next_url=None):
    """Press "Continue with Google", then come back from Google with a code."""
    start = client.post(reverse("google_login"), {"next": next_url} if next_url else {})
    assert start.status_code == 302 and start["Location"].startswith("https://accounts.google.com/")
    state = parse_qs(urlparse(start["Location"]).query)["state"][0]
    return client.get(reverse("google_callback"), {"code": "c", "state": state})


@pytest.mark.django_db
def test_login_page_shows_the_google_button_only_when_set_up(client, settings):
    settings.GOOGLE_CLIENT_ID = ""
    assert "Continue with Google" not in client.get(reverse("login")).content.decode()
    settings.GOOGLE_CLIENT_ID = "test-client"
    settings.SOCIALACCOUNT_PROVIDERS = GOOGLE
    assert "Continue with Google" in client.get(reverse("login")).content.decode()


@pytest.mark.django_db
def test_a_new_google_person_without_an_invite_gets_no_account(client, google):
    response = sign_in_with_google(client)
    assert response.status_code == 403
    assert "No account uses this Google account." in response.content.decode()
    assert not get_user_model().objects.exists() and not SocialAccount.objects.exists()


@pytest.mark.django_db
def test_an_account_with_the_same_email_but_no_linked_google_is_not_signed_in(
    client, google, make_user
):
    make_user("owner", email="traveler@example.com")
    sign_in_with_google(client)
    assert "_auth_user_id" not in client.session
    assert not SocialAccount.objects.exists()


@pytest.mark.django_db
def test_an_account_waiting_for_approval_sees_the_waiting_page(client, google, make_user):
    """Accounts made before personal invites may still wait for the admin's approval."""
    user = make_user("waiting", is_active=False)
    SocialAccount.objects.create(user=user, provider="google", uid="google-123", extra_data={})
    response = sign_in_with_google(client)
    assert response["Location"] == reverse("account_inactive")
    assert "has not approved this account yet" in client.get(response["Location"]).content.decode()
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_a_signed_in_account_connects_google(owner_client, owner, google):
    page = owner_client.get(reverse("socialaccount_connections")).content.decode()
    assert "Connect Google account" in page and "Not linked." in page
    start = owner_client.post(reverse("google_login") + "?process=connect")
    state = parse_qs(urlparse(start["Location"]).query)["state"][0]
    owner_client.get(reverse("google_callback"), {"code": "c", "state": state})
    assert SocialAccount.objects.get(uid="google-123").user == owner
    assert (
        "traveler@example.com"
        in owner_client.get(reverse("socialaccount_connections")).content.decode()
    )
    # From now on the Google account itself signs in, whatever its address.
    google["email"] = "new-address@example.com"
    client = Client()
    sign_in_with_google(client)
    assert client.session["_auth_user_id"] == str(owner.pk)


@pytest.mark.django_db
def test_an_account_without_password_keeps_its_only_google_login(client, google, make_user):
    user = make_user("dara", email="traveler@example.com")
    user.set_unusable_password()
    user.save()
    account = SocialAccount.objects.create(
        user=user, provider="google", uid="google-123", extra_data={}
    )
    sign_in_with_google(client)
    assert client.session["_auth_user_id"] == str(user.pk)
    response = client.post(reverse("socialaccount_connections"), {"account": account.pk})
    assert SocialAccount.objects.filter(pk=account.pk).exists()
    assert "no password" in response.content.decode()


@pytest.mark.django_db
def test_allauth_adds_no_second_password_login_or_reset(client):
    for path in ("/accounts/password/reset/", "/accounts/email/", "/accounts/3rdparty/"):
        assert client.get(path).status_code in (302, 404)
    assert client.get("/accounts/password/reset/").status_code != 200


@pytest.mark.django_db
def test_google_buttons_are_plain_form_posts(owner_client, settings):
    """htmx cannot follow a redirect to another site, so these forms must not be boosted."""
    settings.GOOGLE_CLIENT_ID = "test-client"
    settings.SOCIALACCOUNT_PROVIDERS = GOOGLE
    login = Client().get(reverse("login"), {"next": "/trips/"}).content.decode()
    form = login[login.index('action="/accounts/google/login/') :].split(">", 1)[0]
    assert 'hx-boost="false"' in form and form.count("next=") == 1
    page = owner_client.get(reverse("socialaccount_connections")).content.decode()
    assert 'process=connect" hx-boost="false"' in page
