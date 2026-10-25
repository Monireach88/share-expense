"""The visitor's IP address, used by django-axes to lock repeated failed logins."""

from django.conf import settings
from django.http import HttpRequest


def client_ip(request: HttpRequest) -> str | None:
    """Return the IP from ``CLIENT_IP_HEADER`` when a proxy sets it, else the socket address.

    The last value of a comma-separated header is used: it is the one our own
    proxy added, while earlier values can be typed in by the visitor.
    """
    header = settings.CLIENT_IP_HEADER
    if header:
        value = request.META.get(header, "").split(",")[-1].strip()
        if value:
            return value
    return request.META.get("REMOTE_ADDR")
