from django.contrib.auth.backends import ModelBackend


class CaseInsensitiveBackend(ModelBackend):
    """Sign-in accepts any letter case: usernames are stored in lowercase (spec section 6.1)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get("username")
        if isinstance(username, str):
            username = username.strip().lower()
        return super().authenticate(request, username=username, password=password, **kwargs)
