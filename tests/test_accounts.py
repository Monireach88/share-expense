import pytest
from django.urls import reverse

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db


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
    assert client.get(reverse("signup"))["Location"] == reverse("login")
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


def test_admin_carries_the_app_name(client, make_user):
    admin_user = make_user("boss", is_staff=True, is_superuser=True)
    client.force_login(admin_user)
    assert "Share Expense admin" in client.get(reverse("admin:index")).content.decode()


def test_pages_send_a_content_security_policy_and_a_permissions_policy(client):
    response = client.get(reverse("login"))
    csp = response["Content-Security-Policy"]
    directives = dict(part.strip().split(" ", 1) for part in csp.split(";"))
    assert directives["default-src"] == "'self'"
    assert directives["script-src"] == "'self'"  # No inline scripts and no eval.
    assert directives["frame-ancestors"] == "'none'"
    assert directives["object-src"] == "'none'"
    assert directives["form-action"] == "'self' https://accounts.google.com"
    assert "unsafe-eval" not in csp
    assert "camera=()" in response["Permissions-Policy"]
    assert "geolocation=()" in response["Permissions-Policy"]


def test_htmx_runs_without_eval_and_the_csrf_cookie_is_hidden_from_scripts(client, settings):
    page = client.get(reverse("login")).content.decode()
    assert '"allowEval": false' in page and '"includeIndicatorStyles": false' in page
    assert settings.CSRF_COOKIE_HTTPONLY is True
