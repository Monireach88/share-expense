"""Google sign-in through the real URLs; only the two calls to Google's servers are faked."""

from urllib.parse import parse_qs, urlparse

import pytest
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from django.contrib.auth import get_user_model
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


def sign_in_with_google(client):
    """Press "Continue with Google", then come back from Google with a code."""
    start = client.post(reverse("google_login"))
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
def test_a_new_google_person_waits_for_approval(client, google):
    response = sign_in_with_google(client)
    assert response.status_code == 302 and response["Location"] == reverse("account_inactive")
    user = get_user_model().objects.get(email="traveler@example.com")
    assert not user.is_active and user.first_name == "Dara" and not user.has_usable_password()
    page = client.get(response["Location"]).content.decode()
    assert "sign in with Google" in page
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_an_approved_account_with_the_same_email_signs_in(client, google, make_user):
    owner = make_user("owner", email="traveler@example.com")
    response = sign_in_with_google(client)
    assert response.status_code == 302 and response["Location"] == reverse("home")
    assert client.session["_auth_user_id"] == str(owner.pk)
    assert SocialAccount.objects.get(uid="google-123").user == owner
    # Next time the Google account itself is enough, even if the email changed.
    client.logout()
    google["email"] = "new-address@example.com"
    sign_in_with_google(client)
    assert client.session["_auth_user_id"] == str(owner.pk)


@pytest.mark.django_db
def test_a_signed_in_account_connects_google(owner_client, owner, google):
    page = owner_client.get(reverse("socialaccount_connections")).content.decode()
    assert "Connect Google account" in page
    start = owner_client.post(reverse("google_login") + "?process=connect")
    state = parse_qs(urlparse(start["Location"]).query)["state"][0]
    owner_client.get(reverse("google_callback"), {"code": "c", "state": state})
    assert SocialAccount.objects.get(uid="google-123").user == owner
    assert (
        "traveler@example.com"
        in owner_client.get(reverse("socialaccount_connections")).content.decode()
    )


@pytest.mark.django_db
def test_an_account_without_password_keeps_its_only_google_login(client, google, make_user):
    user = make_user("dara", email="traveler@example.com")
    user.set_unusable_password()
    user.save()
    sign_in_with_google(client)
    account = SocialAccount.objects.get(uid="google-123")
    response = client.post(reverse("socialaccount_connections"), {"account": account.pk})
    assert SocialAccount.objects.filter(pk=account.pk).exists()
    assert "no password" in response.content.decode()


@pytest.mark.django_db
def test_allauth_adds_no_second_password_login_or_reset(client):
    for path in ("/accounts/password/reset/", "/accounts/email/", "/accounts/3rdparty/"):
        assert client.get(path).status_code in (302, 404)
    assert client.get("/accounts/password/reset/").status_code != 200
