from django.conf import settings


def google_signin(request) -> dict:
    """Whether Google sign-in is set up, so pages show its buttons only then."""
    return {"google_signin": bool(settings.GOOGLE_CLIENT_ID)}
