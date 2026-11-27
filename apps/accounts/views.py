from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from apps.trips.invite_views import SESSION_KEY

from .closing import CloseRefused, close_account
from .forms import CloseAccountForm, LoginForm


class LoginView(auth_views.LoginView):
    form_class = LoginForm
    redirect_authenticated_user = True

    def get(self, request, *args, **kwargs):
        # A plain sign-in forgets an invite opened earlier in this browser, so a Google sign-in
        # from here is never mistaken for accepting that invite.
        request.session.pop(SESSION_KEY, None)
        return super().get(request, *args, **kwargs)


@login_not_required
def signup(request: HttpRequest) -> HttpResponse:
    """The old "Request an account" address: new accounts come only from personal invites."""
    return redirect("login")


@login_not_required
def pending(request: HttpRequest) -> HttpResponse:
    """An account made before personal invites that still waits for the admin's approval."""
    return render(request, "registration/pending.html")


def close(request: HttpRequest) -> HttpResponse:
    """Delete account (spec section 6.5): the account is closed, not erased."""
    form = CloseAccountForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            close_account(request.user)
        except CloseRefused as refused:
            form.add_error(None, str(refused))
        else:
            logout(request)
            messages.success(request, _("Your account is closed."))
            return redirect("login")
    return render(request, "registration/close_account.html", {"form": form})


@login_not_required
def health(request: HttpRequest) -> HttpResponse:
    return HttpResponse("ok", content_type="text/plain")
