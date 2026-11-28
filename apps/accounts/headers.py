"""Security headers that Django does not send by itself."""

from django.conf import settings


class PermissionsPolicyMiddleware:
    """Send the Permissions-Policy header (``PERMISSIONS_POLICY`` setting): the browser refuses
    these features to the app and to anything it might load, such as the camera."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.value = ", ".join(f"{feature}=()" for feature in settings.PERMISSIONS_POLICY)

    def __call__(self, request):
        response = self.get_response(request)
        if self.value:
            response.headers.setdefault("Permissions-Policy", self.value)
        return response
