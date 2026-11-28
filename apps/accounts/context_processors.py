from django.conf import settings
from django.utils.functional import SimpleLazyObject


def google_signin(request) -> dict:
    """Whether Google sign-in is set up, so pages show its buttons only then; and the address of
    the Google account linked to the signed-in account, for the account menu ("" when none)."""
    from apps.trips.invites import google_email  # Imported here: apps load after settings.

    user = getattr(request, "user", None)
    return {
        "google_signin": bool(settings.GOOGLE_CLIENT_ID),
        "google_email": SimpleLazyObject(
            lambda: (
                google_email(user, verified_only=False)
                if user is not None and user.is_authenticated
                else ""
            )
        ),
    }


def languages(request) -> dict:
    """The language menu: every language in its own name, and the short name for the button."""
    from django.utils import translation

    from .locale import SHORT_NAMES

    current = translation.get_language() or settings.LANGUAGE_CODE
    return {
        "language_choices": settings.LANGUAGES,
        "language_short": SHORT_NAMES.get(current, current.upper()),
    }
