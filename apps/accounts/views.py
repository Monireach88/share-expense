from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.trips.invite_views import SESSION_KEY

from .closing import CloseRefused, close_account, owner_block
from .forms import CloseAccountForm, LoginForm
from .locale import is_supported, set_cookie
from .models import Appearance


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
    """Close account (spec section 6.5): the account is closed, not erased. An Owner of a trip
    with other accounts sees only why it cannot be closed yet."""
    form = CloseAccountForm(request.POST or None, user=request.user)
    blocked = owner_block(request.user)
    if request.method == "POST" and not blocked and form.is_valid():
        try:
            close_account(request.user)
        except CloseRefused as refused:
            form.add_error(None, str(refused))
        else:
            logout(request)
            messages.success(request, _("Your account is closed."))
            return redirect("login")
    return render(request, "registration/close_account.html", {"form": form, "blocked": blocked})


@login_not_required
def health(request: HttpRequest) -> HttpResponse:
    return HttpResponse("ok", content_type="text/plain")


@require_POST
@login_not_required
def set_language(request: HttpRequest) -> HttpResponse:
    """The header menu: keep the chosen language in the cookie, and in the account when signed
    in, then return to the same page. A ``next`` on another host is ignored."""
    target = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        target = "/"
    response = redirect(target)
    code = request.POST.get("language", "")
    if is_supported(code):
        set_cookie(response, code)
        if request.user.is_authenticated and request.user.language != code:
            request.user.language = code
            request.user.save(update_fields=["language"])
    return response


@require_POST
def set_appearance(request: HttpRequest) -> HttpResponse:
    """Save the person's Light / Dark / System choice and go back to the page they were on."""
    choice = request.POST.get("appearance")
    if choice not in Appearance.values:
        return HttpResponseBadRequest("Unknown appearance")
    if request.user.appearance != choice:
        request.user.appearance = choice
        request.user.save(update_fields=["appearance"])
    target = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        target = "/"
    return redirect(target)
