import pytest
from django.urls import reverse

from apps.accounts.models import Appearance


@pytest.fixture
def url():
    return reverse("set_appearance")


def test_default_is_system(owner):
    assert owner.appearance == Appearance.SYSTEM


@pytest.mark.parametrize("choice", ["light", "dark", "system"])
def test_saves_each_value(owner_client, owner, url, choice):
    owner.appearance = "dark" if choice != "dark" else "light"
    owner.save()
    response = owner_client.post(url, {"appearance": choice, "next": "/"})
    assert response.status_code == 302
    owner.refresh_from_db()
    assert owner.appearance == choice


def test_invalid_value_refused(owner_client, owner, url):
    response = owner_client.post(url, {"appearance": "neon"})
    assert response.status_code == 400
    owner.refresh_from_db()
    assert owner.appearance == "system"


def test_anonymous_goes_to_login(client, url):
    response = client.post(url, {"appearance": "dark"})
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("login"))


def test_next_on_this_site_is_followed(owner_client, url):
    response = owner_client.post(url, {"appearance": "dark", "next": "/password/"})
    assert response["Location"] == "/password/"


@pytest.mark.parametrize("target", ["https://evil.example/x", "//evil.example/x"])
def test_next_to_outside_host_is_ignored(owner_client, url, target):
    response = owner_client.post(url, {"appearance": "dark", "next": target})
    assert response["Location"] == "/"


@pytest.mark.parametrize(
    ("choice", "attribute", "meta"),
    [("light", 'data-theme="light"', "#ffffff"), ("dark", 'data-theme="dark"', "#1a1d23")],
)
def test_forced_theme_is_rendered(owner_client, owner, choice, attribute, meta):
    owner.appearance = choice
    owner.save()
    html = owner_client.get("/").content.decode()
    assert attribute in html
    assert f'<meta name="theme-color" content="{meta}">' in html


def test_system_renders_no_data_theme(owner_client):
    html = owner_client.get("/").content.decode()
    assert "data-theme" not in html
    assert 'media="(prefers-color-scheme: dark)"' in html


def test_menu_marks_current_choice(owner_client, owner):
    owner.appearance = "dark"
    owner.save()
    html = owner_client.get("/").content.decode()
    assert 'value="dark" aria-pressed="true"' in html
    assert 'value="light" aria-pressed="false"' in html
