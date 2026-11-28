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
