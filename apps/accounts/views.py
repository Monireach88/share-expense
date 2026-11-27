from django.contrib.auth.decorators import login_not_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from .forms import SignupRequestForm


@login_not_required
def signup(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("home")
    form = SignupRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return render(request, "registration/signup_sent.html")
    return render(request, "registration/signup.html", {"form": form})


@login_not_required
def pending(request: HttpRequest) -> HttpResponse:
    """After a first Google sign-in: the new account waits for the admin's approval."""
    return render(request, "registration/signup_sent.html", {"google": True})


@login_not_required
def health(request: HttpRequest) -> HttpResponse:
    return HttpResponse("ok", content_type="text/plain")
