from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.trips.models import Trip

from .forms import LoginForm, SignupRequestForm


def pending_join_url(user) -> str | None:
    """The join page of the invite link this account came from, if it still has one."""
    return reverse("join", args=[user.invite_token]) if user.invite_token else None


class LoginView(auth_views.LoginView):
    """After a first sign-in that began at an invite link, go to that link's join page."""

    form_class = LoginForm
    redirect_authenticated_user = True

    def get_default_redirect_url(self):
        return pending_join_url(self.request.user) or super().get_default_redirect_url()


@login_not_required
def signup(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("home")
    token = request.POST.get("invite") or request.GET.get("invite") or ""
    if not Trip.objects.filter(invite_token=token).exists():
        token = ""
    form = SignupRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.invite_token = token  # The first sign-in after approval opens the join page.
        user.save()
        return render(request, "registration/signup_sent.html", {"invite": bool(token)})
    return render(request, "registration/signup.html", {"form": form, "invite": token})


@login_not_required
def pending(request: HttpRequest) -> HttpResponse:
    """After a first Google sign-in: the new account waits for the admin's approval."""
    return render(request, "registration/signup_sent.html", {"google": True})


@login_not_required
def health(request: HttpRequest) -> HttpResponse:
    return HttpResponse("ok", content_type="text/plain")
