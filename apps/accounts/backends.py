from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class AccountClosed(Exception):
    """The password is right but the account is closed (spec section 6.5).

    Not a ``PermissionDenied``: Django's ``authenticate`` would report that as a failed login,
    and django-axes would count it. The login form turns it into the "closed" message.
    """


class CaseInsensitiveBackend(ModelBackend):
    """Sign-in accepts any letter case: usernames are stored in lowercase (spec section 6.1).

    django-axes's backend runs before this one, so a locked login never reaches the password
    check here. The password is hashed once, for every kind of account.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(get_user_model().USERNAME_FIELD)
        if not isinstance(username, str) or password is None:
            return None
        user_model = get_user_model()
        try:
            user = user_model._default_manager.get_by_natural_key(username.strip().lower())
        except user_model.DoesNotExist:
            user_model().set_password(password)  # Same time cost as a real account.
            return None
        if not user.check_password(password):
            return None
        if self.user_can_authenticate(user):
            return user
        if getattr(user, "closed_at", None) is not None:
            raise AccountClosed
        return None
