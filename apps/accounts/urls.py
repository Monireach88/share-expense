from allauth.socialaccount.providers.google.provider import GoogleProvider
from allauth.socialaccount.providers.oauth2.urls import default_urlpatterns
from django.contrib.auth import views as auth_views
from django.urls import include, path

from . import views
from .forms import PlainPasswordChangeForm

login_view = views.LoginView.as_view()

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("login/", login_view, name="login"),
    path("language/", views.set_language, name="set_language"),
    path("close/", views.close, name="account_close"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "password/",
        auth_views.PasswordChangeView.as_view(form_class=PlainPasswordChangeForm),
        name="password_change",
    ),
    path(
        "password/done/", auth_views.PasswordChangeDoneView.as_view(), name="password_change_done"
    ),
    # Google sign-in (django-allauth): only Google and its connection pages are routed, so allauth
    # adds no second password login. allauth links to its pages by these names.
    *default_urlpatterns(GoogleProvider),
    path("google/", include("allauth.socialaccount.urls")),
    path("login/", login_view, name="account_login"),
    path("signup/", views.signup, name="account_signup"),
    path("pending/", views.pending, name="account_inactive"),
]
