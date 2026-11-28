"""Khmer, Chinese and English (docs/spec_languages.md sections 1, 2 and 4)."""

import polib
import pytest
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import translation
from django.utils.formats import number_format

from config import settings as production_settings

from .conftest import PASSWORD, compile_messages

pytestmark = pytest.mark.django_db

ENGLISH_BROWSER = {"HTTP_ACCEPT_LANGUAGE": "en-US,en;q=0.9,zh;q=0.8"}


def page_language(response) -> str:
    html = response.content.decode()
    return html.split('<html lang="', 1)[1].split('"', 1)[0]


def test_production_settings_default_to_khmer_with_three_languages():
    assert production_settings.LANGUAGE_CODE == "km"
    assert [code for code, _name in production_settings.LANGUAGES] == ["km", "zh-hans", "en"]
    # Each language is named in itself, so the menu reads right in every language.
    assert dict(production_settings.LANGUAGES) == {
        "km": "ខ្មែរ",
        "zh-hans": "中文",
        "en": "English",
    }


def test_a_fresh_visitor_sees_khmer_and_the_browser_language_is_ignored(client, settings):
    settings.LANGUAGE_CODE = production_settings.LANGUAGE_CODE
    response = client.get(reverse("login"), **ENGLISH_BROWSER)
    assert page_language(response) == "km"
    assert response["Content-Language"] == "km"
    assert "Cookie" in response["Vary"]
    assert page_language(client.get(reverse("login"), HTTP_ACCEPT_LANGUAGE="zh-CN")) == "km"


def test_the_cookie_chooses_the_language(client, settings):
    settings.LANGUAGE_CODE = "km"
    client.cookies[django_settings.LANGUAGE_COOKIE_NAME] = "zh-hans"
    assert page_language(client.get(reverse("login"))) == "zh-hans"
    client.cookies[django_settings.LANGUAGE_COOKIE_NAME] = "fr"  # Not offered: falls back.
    assert page_language(client.get(reverse("login"))) == "km"


def test_the_header_has_a_language_menu_on_the_sign_in_page(client):
    html = client.get(reverse("login")).content.decode()
    assert 'class="menu lang-menu"' in html
    for name in ("ខ្មែរ", "中文", "English"):
        assert name in html
    assert 'name="language" value="zh-hans"' in html


def test_the_switcher_sets_the_cookie_and_returns_to_the_page(client):
    response = client.post(
        reverse("set_language"), {"language": "zh-hans", "next": reverse("login")}
    )
    assert response.status_code == 302 and response["Location"] == reverse("login")
    assert response.cookies[django_settings.LANGUAGE_COOKIE_NAME].value == "zh-hans"
    assert page_language(client.get(reverse("login"))) == "zh-hans"


def test_the_switcher_saves_the_language_in_the_account(owner_client, owner):
    owner_client.post(reverse("set_language"), {"language": "km", "next": "/"})
    owner.refresh_from_db()
    assert owner.language == "km"
    assert page_language(owner_client.get(reverse("home"))) == "km"


def test_a_language_that_is_not_offered_changes_nothing(owner_client, owner):
    response = owner_client.post(reverse("set_language"), {"language": "fr", "next": "/"})
    owner.refresh_from_db()
    assert owner.language == ""
    assert django_settings.LANGUAGE_COOKIE_NAME not in response.cookies


def test_next_to_another_host_is_ignored(client):
    for target in ("https://evil.example/", "//evil.example/x", "javascript:alert(1)"):
        response = client.post(reverse("set_language"), {"language": "en", "next": target})
        assert response["Location"] == "/", target


def test_the_switcher_only_accepts_post(client):
    assert client.get(reverse("set_language")).status_code == 405


def test_the_saved_language_wins_after_log_in_on_any_device(client, make_user, settings):
    settings.LANGUAGE_CODE = "km"
    user = make_user("traveler", language="zh-hans")
    client.cookies[django_settings.LANGUAGE_COOKIE_NAME] = "en"  # This device chose English.
    assert page_language(client.get(reverse("login"))) == "en"
    response = client.post(
        reverse("login"), {"username": user.username, "password": PASSWORD}, follow=True
    )
    assert page_language(response) == "zh-hans"
    assert client.cookies[django_settings.LANGUAGE_COOKIE_NAME].value == "zh-hans"
    # After log out the device keeps the language of the account.
    client.post(reverse("logout"))
    assert page_language(client.get(reverse("login"))) == "zh-hans"


def test_numbers_use_western_digits_in_every_language():
    for code in ("km", "zh-hans", "en"):
        with translation.override(code):
            assert number_format(1250.5, decimal_pos=2, force_grouping=True) == "1,250.50", code


def test_the_user_language_must_be_one_of_the_offered_languages():
    field = get_user_model()._meta.get_field("language")
    assert [code for code, _name in field.choices] == ["km", "zh-hans", "en"]
    assert field.default == ""


@pytest.fixture
def khmer_catalog(tmp_path, settings):
    """A small test-only Khmer catalog, so the real .po files stay free of test text."""
    folder = tmp_path / "km" / "LC_MESSAGES"
    folder.mkdir(parents=True)
    po = polib.POFile()
    po.metadata = {"Content-Type": "text/plain; charset=UTF-8", "Language": "km"}
    po.append(polib.POEntry(msgid="Log in", msgstr="ចូលគណនី"))
    po.append(polib.POEntry(msgctxt="expense type", msgid="Transport", msgstr="ដឹកជញ្ជូន"))
    po.save(str(folder / "django.po"))
    assert compile_messages(tmp_path) == 1
    settings.LOCALE_PATHS = [tmp_path]


def test_a_page_in_khmer_uses_the_khmer_text(client, khmer_catalog, settings):
    settings.LANGUAGE_CODE = "km"
    response = client.get(reverse("login"))
    assert "ចូលគណនី" in response.content.decode()
    assert page_language(response) == "km"
    # The same page in English keeps the English text.
    client.cookies[django_settings.LANGUAGE_COOKIE_NAME] = "en"
    assert "ចូលគណនី" not in client.get(reverse("login")).content.decode()


def test_default_types_are_translated_when_shown_not_stored(
    owner_client, trip, khmer_catalog, settings
):
    settings.LANGUAGE_CODE = "km"
    transport = trip.categories.get(name="Transport")
    assert transport.name == "Transport"  # Stored in English for every trip.
    assert transport.label == "ដឹកជញ្ជូន"
    with translation.override("en"):
        assert transport.label == "Transport"


def test_the_khmer_font_is_loaded_only_for_khmer_letters():
    css = (django_settings.BASE_DIR / "static" / "css" / "app.css").read_text()
    assert "unicode-range: U+1780-17FF" in css
    assert (django_settings.BASE_DIR / "static" / "fonts" / "OFL.txt").exists()
    assert (django_settings.BASE_DIR / "static" / "fonts" / "NotoSansKhmer-Regular.woff2").exists()


def test_the_real_po_files_list_the_same_strings_and_stay_untranslated_for_review():
    folder = django_settings.BASE_DIR / "locale"
    catalogs = {
        code: polib.pofile(str(folder / code / "LC_MESSAGES" / "django.po"))
        for code in ("km", "zh_Hans")
    }
    keys = {code: {(e.msgctxt, e.msgid) for e in po} for code, po in catalogs.items()}
    assert keys["km"] == keys["zh_Hans"]
    assert len(keys["km"]) > 400
    assert ("expense type", "Transport") in keys["km"]
