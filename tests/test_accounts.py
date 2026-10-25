import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_signup_creates_inactive_account_that_cannot_log_in(client):
    response = client.post(
        reverse("signup"),
        {"username": "newbie", "first_name": "New", "password1": PASSWORD, "password2": PASSWORD},
    )
    assert response.status_code == 200
    assert b"Request sent" in response.content
    user = get_user_model().objects.get(username="newbie")
    assert not user.is_active
    login = client.post(reverse("login"), {"username": "newbie", "password": PASSWORD})
    assert login.status_code == 200
    assert "_auth_user_id" not in client.session


def test_admin_approval_lets_the_user_log_in(client, make_user):
    admin = make_user("boss", is_staff=True, is_superuser=True)
    pending = make_user("pending", is_active=False)
    client.force_login(admin)
    client.post(
        reverse("admin:accounts_user_changelist"),
        {"action": "approve", "_selected_action": [pending.pk]},
    )
    pending.refresh_from_db()
    assert pending.is_active
    client.logout()
    response = client.post(reverse("login"), {"username": "pending", "password": PASSWORD})
    assert response.status_code == 302


def test_every_page_requires_login_except_auth_pages(client, trip):
    for url in [
        reverse("home"),
        reverse("trip", args=[trip.id]),
        reverse("summary", args=[trip.id]),
    ]:
        response = client.get(url)
        assert response.status_code == 302
        assert response.url.startswith(reverse("login"))
    assert client.get(reverse("signup")).status_code == 200
    assert client.get(reverse("health")).status_code == 200


def test_login_is_locked_after_five_failures(client, make_user):
    make_user("victim")
    for _ in range(5):
        client.post(reverse("login"), {"username": "victim", "password": "wrong"})
    response = client.post(reverse("login"), {"username": "victim", "password": PASSWORD})
    assert response.status_code == 429


def test_lock_uses_the_ip_our_proxy_added(rf, settings):
    from apps.accounts.client_ip import client_ip

    settings.CLIENT_IP_HEADER = "HTTP_X_FORWARDED_FOR"
    spoofed = rf.get("/", HTTP_X_FORWARDED_FOR="1.1.1.1, 203.0.113.9", REMOTE_ADDR="172.18.0.2")
    assert client_ip(spoofed) == "203.0.113.9"
    assert client_ip(rf.get("/", REMOTE_ADDR="172.18.0.2")) == "172.18.0.2"
    settings.CLIENT_IP_HEADER = ""
    assert client_ip(spoofed) == "172.18.0.2"


def test_lock_is_per_ip(client, make_user, settings):
    settings.CLIENT_IP_HEADER = "HTTP_X_FORWARDED_FOR"
    make_user("victim")
    for _ in range(5):
        client.post(
            reverse("login"),
            {"username": "victim", "password": "x"},
            HTTP_X_FORWARDED_FOR="198.51.100.1",
        )
    other_ip = {"HTTP_X_FORWARDED_FOR": "198.51.100.2"}
    response = client.post(
        reverse("login"), {"username": "victim", "password": PASSWORD}, **other_ip
    )
    assert response.status_code == 302
