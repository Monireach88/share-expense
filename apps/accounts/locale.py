"""Which language a page is written in (spec_languages.md L2).

The language is the signed-in account's saved choice (``User.language``), else the
``django_language`` cookie, else ``settings.LANGUAGE_CODE`` (Khmer). The browser's
Accept-Language header is never read, so a visitor sees Khmer until they choose another language.
Django's own LocaleMiddleware is not used because it reads that header.
"""

from django.conf import settings
from django.utils import translation
from django.utils.cache import patch_vary_headers

# The text on the header button; a language without an entry shows its upper-case code.
SHORT_NAMES = {"km": "ខ្មែរ", "zh-hans": "中文", "en": "EN"}


def is_supported(code: str) -> bool:
    return code in dict(settings.LANGUAGES)


def set_cookie(response, code: str) -> None:
    response.set_cookie(
        settings.LANGUAGE_COOKIE_NAME,
        code,
        max_age=settings.LANGUAGE_COOKIE_AGE,
        samesite=settings.LANGUAGE_COOKIE_SAMESITE,
        secure=settings.LANGUAGE_COOKIE_SECURE,
        httponly=False,
    )


class LanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        saved = getattr(user, "language", "") if user is not None and user.is_authenticated else ""
        cookie = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME, "")
        if is_supported(saved):
            language = saved
        elif is_supported(cookie):
            language = cookie
        else:
            language = settings.LANGUAGE_CODE
        translation.activate(language)
        request.LANGUAGE_CODE = translation.get_language()
        response = self.get_response(request)
        if is_supported(saved) and cookie != saved:
            set_cookie(response, saved)  # The account's choice also covers pages after log out.
        response.headers.setdefault("Content-Language", language)
        patch_vary_headers(response, ("Cookie",))
        return response
