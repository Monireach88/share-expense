"""Personal invites, Google-only new accounts, leaving a trip, closing an account and the invite
email (spec sections 4 and 6.2 to 6.6).

Uses the crew of ``test_roles``: Ann owns "Crew trip"; Ben is an Editor; Cara and Dan are
Members; Eve is a Member with no traveler; Sam has an account but is not on the trip. Gina is a
new person with no account yet. Every address is at example.com.
"""

import re
import smtplib
from datetime import timedelta
from pathlib import Path

import pytest
from allauth.socialaccount.models import SocialAccount
from axes.models import AccessAttempt
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.disputes import rules
from apps.disputes.models import Notification
from apps.trips import history
from apps.trips.models import (
    HistoryEntry,
    Invite,
    InviteEmailAttempt,
    Participant,
    Trip,
    TripMember,
)

from .conftest import PASSWORD
from .test_google import google, sign_in_with_google  # noqa: F401
from .test_roles import Crew

pytestmark = pytest.mark.django_db

User = get_user_model()
LINK = re.compile(r"/invite/([A-Za-z0-9_-]{40,})/")
GONE = "Ask the Owner of the trip for a new one."


@pytest.fixture
def crew(db):
    return Crew()


@pytest.fixture
def email_on(settings):
    """An SMTP host is set; Django's in-memory backend catches what would be sent."""
    settings.EMAIL_HOST = "smtp.example.com"
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    return mail.outbox


def texts(trip) -> list[str]:
    return [history.describe(e) for e in HistoryEntry.objects.filter(trip=trip).order_by("id")]


def notes(user) -> list[str]:
    return [rules.notification_text(n) for n in Notification.objects.visible_to(user)]


def post_invite(crew, who, traveler="none", *, confirm=True, by="ann", client=None, **extra):
    data = {"who": who, "traveler": traveler, **extra}
    if confirm:
        data["confirm"] = "1"
    return (client or crew.client(by)).post(crew.url("invite_new"), data, follow=confirm)


def invite_link(crew, who="gina@example.com", traveler="none", **extra) -> str:
    """Invite an address and return the link the Travelers page then shows the Owner."""
    page = post_invite(crew, who, traveler, **extra).content.decode()
    match = LINK.search(page)
    assert match, page[:800]
    return match.group(0)


def the_invite(crew) -> Invite:
    return Invite.objects.get(trip=crew.trip)


def link_google(user, email, uid="google-123"):
    return SocialAccount.objects.create(
        user=user, provider="google", uid=uid, extra_data={"email": email, "email_verified": True}
    )


def accept_with_google(client, link, google, email):  # noqa: F811
    """Open the invite link, continue with Google as ``email``, and follow where it leads."""
    google["email"] = email
    page = client.get(link)
    assert page.status_code == 200
    response = sign_in_with_google(client, link)
    while response.status_code == 302 and response["Location"].startswith("/"):
        response = client.get(response["Location"])
    return response


# --- 6.2 Inviting a person ----------------------------------------------------------------------


def test_inviting_an_existing_account_by_username_adds_it_at_once(crew):
    fay = Participant.objects.create(trip=crew.trip, name="Fay")
    ask = post_invite(crew, "SAM", str(fay.pk), confirm=False).content.decode()
    assert "Add Sam (sam) to this trip now?" in ask and "As Fay" in ask
    assert not TripMember.objects.filter(trip=crew.trip, user=crew.users["sam"]).exists()
    response = post_invite(crew, "SAM", str(fay.pk))
    assert response.redirect_chain[-1][0] == crew.url("people")
    member = TripMember.objects.get(trip=crew.trip, user=crew.users["sam"])
    assert member.role == TripMember.Role.MEMBER and member.linked_traveler == fay
    assert texts(crew.trip) == ["Ann added Sam's account", "Ann linked traveler Fay to account Sam"]
    assert notes(crew.users["sam"]) == ["Ann added you to the trip"]
    assert Notification.objects.get(user=crew.users["sam"]).link == crew.url("trip")
    assert not Invite.objects.exists()


def test_inviting_the_google_address_of_an_approved_account_adds_it(crew):
    link_google(crew.users["sam"], "sam@example.com")
    ask = post_invite(crew, "Sam@Example.com", confirm=False).content.decode()
    assert "Add Sam (sam) to this trip now?" in ask and "As Viewer" in ask
    post_invite(crew, "Sam@Example.com", "new", new_name="Sammy")
    member = TripMember.objects.get(trip=crew.trip, user=crew.users["sam"])
    assert member.linked_traveler.name == "Sammy"
    assert texts(crew.trip) == ["Ann added traveler Sammy", "Ann added Sam's account"]


def test_inviting_a_new_person_by_email(crew, email_on):
    ask = post_invite(crew, " gina@example.com ", "new", confirm=False, new_name="Gina")
    assert "Invite gina@example.com?" in ask.content.decode()
    assert "As new traveler Gina" in ask.content.decode()
    assert not Invite.objects.exists()
    page = post_invite(crew, "gina@example.com", "new", new_name="Gina").content.decode()
    invite = the_invite(crew)
    assert invite.email == "gina@example.com" and invite.state == Invite.State.PENDING
    assert invite.new_traveler_name == "Gina" and invite.invited_by == crew.users["ann"]
    # The link is shown with a Copy button (browsers copy only right after a tap).
    link = LINK.search(page).group(0)
    assert f'value="http://testserver{link}" readonly' in page and "data-copy=" in page
    assert len(email_on) == 1 and email_on[0].to == ["gina@example.com"]
    assert "The invite email was sent to gina@example.com." in page
    expires = timezone.localtime(invite.expires_at)
    when = f"{expires.day} {expires:%b} {expires.year} at {expires:%H:%M}"
    assert f"This link works once and expires on {when}." in page
    assert f"As Gina · expires on {when}" in page
    assert texts(crew.trip) == ["Ann invited g***@example.com as Gina"]
    assert crew.trip.participants.filter(name="Gina").count() == 0  # Made when accepted.


def test_only_the_hash_of_the_token_is_stored(crew):
    link = invite_link(crew)
    token = LINK.search(link).group(1)
    assert len(token) >= 43  # 32 random bytes, URL-safe.
    invite = the_invite(crew)
    assert invite.token_hash != token and len(invite.token_hash) == 64
    assert token not in str(Invite.objects.values().get())


def test_any_other_text_is_not_an_account(crew):
    page = post_invite(crew, "nobody_here", confirm=False).content.decode()
    assert "No account has this username. To invite someone new, type their email address." in page
    page = post_invite(crew, "not an@address", confirm=False).content.decode()
    assert "No account has this username." in page
    assert not Invite.objects.exists()


def test_a_person_already_on_the_trip(crew):
    link_google(crew.users["cara"], "cara@example.com")
    for who in ("cara", "CARA", "cara@example.com"):
        page = post_invite(crew, who, confirm=False).content.decode()
        assert "This person is already on the trip." in page
    post_invite(crew, "cara")
    assert TripMember.objects.filter(trip=crew.trip, user=crew.users["cara"]).count() == 1


def test_an_address_with_a_pending_invite_offers_send_again(crew):
    invite_link(crew)
    page = post_invite(crew, "GINA@example.com", confirm=False).content.decode()
    invite = the_invite(crew)
    assert "This address already has an invite to this trip." in page
    assert crew.url("invite_resend", invite.pk) in page and "Send the invite again" in page
    post_invite(crew, "GINA@example.com")
    assert Invite.objects.count() == 1
    with pytest.raises(IntegrityError):
        Invite.objects.create(
            trip=crew.trip, email="Gina@Example.com", token_hash="x" * 64, expires_at=timezone.now()
        )


def test_the_traveler_choices(crew):
    fay = Participant.objects.create(trip=crew.trip, name="Fay")
    gus = Participant.objects.create(trip=crew.trip, name="Gus")
    invite_link(crew, "gus@example.com", str(gus.pk))
    page = crew.client("ann").get(crew.url("invite_new")).content.decode()
    assert f'value="{fay.pk}"' in page and f'value="{gus.pk}"' not in page  # Gus is invited.
    assert f'value="{crew.travelers["dan"].pk}"' not in page  # Dan has an account.
    assert "A new traveler" in page and "No traveler (view only)" in page
    assert "This field is required." in post_invite(crew, "x@example.com", "").content.decode()
    nameless = post_invite(crew, "x@example.com", "new", confirm=False).content.decode()
    assert "Type the new traveler&#x27;s name." in nameless
    taken = post_invite(crew, "x@example.com", "new", confirm=False, new_name="fay")
    assert "Someone on this trip already has this name." in taken.content.decode()
    bad = post_invite(crew, "x@example.com", str(crew.travelers["dan"].pk), confirm=False)
    assert "Select a valid choice" in bad.content.decode()


def test_a_settled_trip_offers_no_new_traveler(crew):
    crew.trip.settled_at = timezone.now()
    crew.trip.save()
    page = crew.client("ann").get(crew.url("invite_new")).content.decode()
    assert "A new traveler" not in page and "No traveler (view only)" in page
    refused = post_invite(crew, "x@example.com", "new", confirm=False, new_name="Xia")
    assert "Select a valid choice" in refused.content.decode()
    invite_link(crew, "x@example.com", "none")  # View only is still allowed.


def test_only_the_owner_invites_and_manages_invites(crew):
    invite_link(crew)
    invite = the_invite(crew)
    urls = [crew.url("invite_new")] + [
        crew.url(name, invite.pk) for name in ("invite_copy", "invite_resend", "invite_cancel")
    ]
    for who, status in (("ben", 403), ("cara", 403), ("eve", 403), ("sam", 404)):
        for url in urls:
            assert crew.client(who).post(url, {"who": "x@example.com"}).status_code == status
        assert "gina@example.com" not in crew.client(who).get(crew.url("people")).content.decode()
    assert Invite.objects.count() == 1 and the_invite(crew).state == Invite.State.PENDING


def test_copy_link_ends_the_old_link(crew, email_on):
    old = invite_link(crew)
    before = the_invite(crew).expires_at
    page = crew.client("ann").post(crew.url("invite_copy", the_invite(crew).pk), follow=True)
    new = LINK.search(page.content.decode()).group(0)
    assert new != old
    assert GONE in Client().get(old).content.decode()
    assert "Crew trip" in Client().get(new).content.decode()
    assert the_invite(crew).expires_at > before  # The 7 days start again.
    assert len(email_on) == 1  # A copy sends nothing.


def test_send_again_on_an_expired_invite(crew, email_on):
    old = invite_link(crew)
    Invite.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    assert GONE in Client().get(old).content.decode()
    assert the_invite(crew).state == Invite.State.EXPIRED
    assert texts(crew.trip)[-1] == "The invite for g***@example.com expired"
    Client().get(old)  # Opening it again records nothing more.
    assert len(texts(crew.trip)) == 2
    assert "Expired" in crew.client("ann").get(crew.url("people")).content.decode()
    page = crew.client("ann").post(crew.url("invite_resend", the_invite(crew).pk), follow=True)
    html = page.content.decode()
    new = LINK.search(html).group(0)
    assert new != old and "As Viewer · expires on " in html
    assert the_invite(crew).state == Invite.State.PENDING and len(email_on) == 2
    assert new in email_on[-1].body
    assert texts(crew.trip)[-1] == "Ann sent the invite for g***@example.com again"
    assert "Crew trip" in Client().get(new).content.decode()


def test_cancel_an_invite(crew):
    link = invite_link(crew)
    crew.client("ann").post(crew.url("invite_cancel", the_invite(crew).pk))
    assert the_invite(crew).state == Invite.State.CANCELLED
    assert GONE in Client().get(link).content.decode()
    assert "gina@example.com" not in crew.client("ann").get(crew.url("people")).content.decode()
    assert texts(crew.trip)[-1] == "Ann cancelled the invite for g***@example.com"
    invite_link(crew)  # The address can be invited again.
    assert Invite.objects.filter(state=Invite.State.PENDING).count() == 1


def test_history_hides_the_address_and_the_owner_list_shows_it(crew):
    invite_link(crew, "gina@example.com", "new", new_name="Gina")
    owner_page = crew.client("ann").get(crew.url("people"))
    assert "gina@example.com" in owner_page.content.decode()
    assert "X-SW-Cache" not in owner_page  # Addresses and links are not kept by the browser.
    for who in ("ann", "cara"):
        html = crew.client(who).get(crew.url("history")).content.decode()
        assert "Ann invited g***@example.com as Gina" in html and "gina@example.com" not in html
    assert "gina@example.com" not in str(HistoryEntry.objects.values().get())
    found = crew.client("ann").get(crew.url("history"), {"q": "invited"}).content.decode()
    assert "g***@example.com" in found


def test_pending_invites_move_with_ownership(crew):
    invite_link(crew)
    crew.client("ann").post(crew.url("member_transfer", crew.members["ben"].id))
    invite = the_invite(crew)
    assert crew.client("ann").post(crew.url("invite_cancel", invite.pk)).status_code == 403
    assert "gina@example.com" in crew.client("ben").get(crew.url("people")).content.decode()
    crew.client("ben").post(crew.url("invite_cancel", invite.pk))
    assert the_invite(crew).state == Invite.State.CANCELLED


def test_deleting_a_trip_deletes_its_invites(crew):
    invite_link(crew)
    crew.client("ann").post(crew.url("trip_delete"))
    assert not Invite.objects.exists()


# --- 6.3 Accepting a personal invite ------------------------------------------------------------


def test_accepting_with_the_invited_google_account(crew, google):  # noqa: F811
    link = invite_link(crew, "Gina@Example.com", "new", new_name="Gina")
    google["given_name"] = "Gina"
    visitor = Client()
    page = visitor.get(link).content.decode()
    assert "Crew trip" in page and "Ann" in page and "g***@example.com" in page
    assert "Continue with Google" in page
    for secret in ("Taxi", "Dan", "Cara", "Ben"):
        assert secret not in page
    response = accept_with_google(visitor, link, google, "gina@EXAMPLE.com")
    assert response.request["PATH_INFO"] == crew.url("trip")
    gina = User.objects.get(username="gina")
    assert gina.is_active and gina.closed_at is None and not gina.has_usable_password()
    member = TripMember.objects.get(trip=crew.trip, user=gina)
    assert member.role == TripMember.Role.MEMBER and member.linked_traveler.name == "Gina"
    invite = the_invite(crew)
    assert invite.state == Invite.State.ACCEPTED and invite.accepted_by == gina
    assert texts(crew.trip)[1:] == [
        "Ann added traveler Gina",
        "Gina accepted the invite for g***@example.com as Gina",
    ]
    assert notes(crew.users["ann"]) == ["Gina accepted your invite"]
    # The invite works once.
    assert GONE in Client().get(link).content.decode()
    assert visitor.get(link)["Location"] == crew.url("trip")  # Already on the trip.


def test_an_account_that_already_uses_the_google_account_joins(crew, google):  # noqa: F811
    link_google(crew.users["sam"], "old-address@example.com")
    fay = Participant.objects.create(trip=crew.trip, name="Fay")
    link = invite_link(crew, "sam.new@example.com", str(fay.pk))
    accept_with_google(Client(), link, google, "sam.new@example.com")
    member = TripMember.objects.get(trip=crew.trip, user=crew.users["sam"])
    assert member.linked_traveler == fay
    assert User.objects.count() == 6  # Nobody new.
    assert texts(crew.trip)[-1] == "Sam accepted the invite for s***@example.com as Fay"


def test_an_address_the_admin_typed_into_another_account_can_still_accept(crew, google):  # noqa: F811
    """Addresses never identify accounts, so a stored copy of it does not block the invite."""
    User.objects.filter(pk=crew.users["eve"].pk).update(email="gina@example.com")
    accept_with_google(Client(), invite_link(crew), google, "gina@example.com")
    gina = TripMember.objects.get(trip=crew.trip, user__username="gina").user
    assert gina != crew.users["eve"] and gina.socialaccount_set.get().uid == "google-123"


def test_the_sign_in_page_forgets_an_opened_invite(crew, google):  # noqa: F811
    link_google(crew.users["sam"], "sam@example.com")
    visitor = Client()
    visitor.get(invite_link(crew))  # An invite for another address.
    visitor.get(reverse("login"))
    google["email"] = "sam@example.com"
    sign_in_with_google(visitor)
    assert visitor.session["_auth_user_id"] == str(crew.users["sam"].pk)


def test_a_leaked_link_is_useless_to_a_stranger(crew, google):  # noqa: F811
    link = invite_link(crew)
    visitor = Client()
    page = accept_with_google(visitor, link, google, "eve.stranger@example.com").content.decode()
    assert (
        "This invite is for g***@example.com, but you used another Google account. Sign out of "
        "Google, then open the invite link again and choose the invited address." in page
    )
    assert User.objects.count() == 6 and not SocialAccount.objects.exists()
    assert "_auth_user_id" not in visitor.session
    assert the_invite(crew).state == Invite.State.PENDING


def test_the_wrong_google_account_of_an_existing_account_joins_nothing(crew, google):  # noqa: F811
    link_google(crew.users["sam"], "sam@example.com")
    link = invite_link(crew)
    visitor = Client()
    page = accept_with_google(visitor, link, google, "sam@example.com").content.decode()
    assert "This invite is for g***@example.com, but you used another Google account." in page
    assert "_auth_user_id" not in visitor.session
    assert not TripMember.objects.filter(trip=crew.trip, user=crew.users["sam"]).exists()


def test_an_expired_invite(crew):
    link = invite_link(crew)
    Invite.objects.update(created_at=timezone.now() - timedelta(days=8))
    Invite.objects.update(expires_at=timezone.now() - timedelta(days=1))
    response = Client().get(link)
    assert GONE in response.content.decode() and "Crew trip" not in response.content.decode()


def test_unknown_tokens_show_nothing(crew):
    response = Client().get(reverse("invite", args=["x" * 43]))
    assert response.status_code == 404 and GONE in response.content.decode()


def test_signed_in_as_another_account(crew):
    link = invite_link(crew)
    page = crew.client("sam").get(link).content.decode()
    assert "You are logged in as Sam. Log out first, then open this link again." in page
    assert not TripMember.objects.filter(trip=crew.trip, user=crew.users["sam"]).exists()


def test_signed_in_with_the_invited_google_address_accepts_at_once(crew):
    link = invite_link(crew, "sam@example.com")  # No account uses this address yet.
    link_google(crew.users["sam"], "SAM@example.com")  # Sam links Google afterwards.
    response = crew.client("sam").get(link)
    assert response.status_code == 302 and response["Location"] == crew.url("trip")
    assert TripMember.objects.get(trip=crew.trip, user=crew.users["sam"]).is_viewer


def test_an_account_already_on_the_trip_is_taken_to_it(crew):
    link = invite_link(crew)
    assert crew.client("cara").get(link)["Location"] == crew.url("trip")


@pytest.mark.parametrize("meanwhile", ["linked", "removed"])
def test_a_traveler_linked_or_removed_meanwhile_joins_as_view_only(crew, google, meanwhile):  # noqa: F811
    fay = Participant.objects.create(trip=crew.trip, name="Fay")
    link = invite_link(crew, "gina@example.com", str(fay.pk))
    if meanwhile == "linked":
        Participant.objects.filter(pk=fay.pk).update(user=crew.users["eve"])
    else:
        crew.client("ann").post(crew.url("participant_delete", fay.pk))
    google["given_name"] = "Gina"
    accept_with_google(Client(), link, google, "gina@example.com")
    member = TripMember.objects.get(trip=crew.trip, user__username="gina")
    assert member.is_viewer
    assert texts(crew.trip)[-1] == "Gina accepted the invite for g***@example.com (view only)"
    assert notes(crew.users["ann"]) == [
        "Gina accepted your invite, but traveler Fay could not be linked. Link the right "
        "traveler on the Travelers page.",
        "Gina accepted your invite",
    ]


def test_a_closed_account_cannot_accept_an_invite(crew, google):  # noqa: F811
    sam = crew.users["sam"]
    link_google(sam, "sam@example.com")
    User.objects.filter(pk=sam.pk).update(is_active=False, closed_at=timezone.now())
    link = invite_link(crew, "sam@example.com")  # A closed account is not added at once.
    visitor = Client()
    page = accept_with_google(visitor, link, google, "sam@example.com").content.decode()
    assert "This account is closed. Ask the admin to restore it." in page
    assert "_auth_user_id" not in visitor.session
    assert not TripMember.objects.filter(trip=crew.trip, user=sam).exists()


def test_a_removed_account_can_be_invited_again(crew):
    crew.client("ann").post(crew.url("member_remove", crew.members["dan"].id))
    post_invite(crew, "dan", str(crew.travelers["dan"].pk))
    member = TripMember.objects.get(trip=crew.trip, user=crew.users["dan"])
    assert member.linked_traveler == crew.travelers["dan"]


# --- 6.4 Signing in and creating accounts -------------------------------------------------------


def test_google_settings_match_by_the_google_account_only():
    assert django_settings.SOCIALACCOUNT_EMAIL_AUTHENTICATION is False
    assert django_settings.SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT is False


def test_google_sign_in_without_an_invite_is_refused(client, google, crew):  # noqa: F811
    google["email"] = "x@example.com"
    response = sign_in_with_google(client)
    page = response.content.decode()
    assert (
        "No account uses this Google account. If you have a username and password, log in with "
        "them and link Google from the account menu. To join a trip, ask its Owner for an invite."
        in page
    )
    assert User.objects.count() == 6 and not SocialAccount.objects.exists()
    assert "_auth_user_id" not in client.session


def test_a_typed_email_cannot_take_over_an_account(client, google, make_user):  # noqa: F811
    cara = make_user("cara", email="cara@example.com")
    google["email"] = "cara@example.com"
    response = sign_in_with_google(client)
    assert "No account uses this Google account." in response.content.decode()
    assert "_auth_user_id" not in client.session and not SocialAccount.objects.exists()
    cara.refresh_from_db()
    assert cara.has_usable_password()
    login = Client().post(reverse("login"), {"username": "cara", "password": PASSWORD})
    assert login.status_code == 302


def test_a_linked_google_account_signs_in_even_after_its_address_changed(client, google, crew):  # noqa: F811
    link_google(crew.users["sam"], "sam@example.com")
    google["email"] = "sam.other@example.com"
    response = sign_in_with_google(client)
    assert response["Location"] == reverse("home")
    assert client.session["_auth_user_id"] == str(crew.users["sam"].pk)


def test_old_shared_links_are_dead(client, crew):
    for path in ("/join/abc123/", "/join/" + "y" * 32 + "/"):
        response = client.get(path)
        assert "This invite no longer works" in response.content.decode()
        assert "Go to my trips" not in response.content.decode()  # Not logged in.
    assert "Crew trip" not in crew.client("sam").get("/join/abc/").content.decode()


def test_the_old_sign_up_address_goes_to_the_sign_in_page(client):
    response = client.get("/accounts/signup/")
    assert response.status_code == 302 and response["Location"] == reverse("login")
    assert client.post("/accounts/signup/", {"username": "x"}).status_code == 302
    page = client.get(reverse("login")).content.decode()
    assert "Request one" not in page and "/accounts/signup/" not in page


def test_a_member_leaves_the_trip(crew):
    cara = crew.client("cara")
    page = cara.get(crew.url("people")).content.decode()
    assert "Leave this trip" in page and "the traveler Cara is unlinked" in page
    viewer = crew.client("eve").get(crew.url("people")).content.decode()
    assert "Leave this trip? You will no longer see it. Only the Owner can add you again." in viewer
    assert "Leave this trip" not in crew.client("ann").get(crew.url("people")).content.decode()
    response = cara.post(crew.url("trip_leave"))
    assert response["Location"] == reverse("home")
    assert not TripMember.objects.filter(trip=crew.trip, user=crew.users["cara"]).exists()
    assert Participant.objects.get(pk=crew.travelers["cara"].pk).user is None
    assert texts(crew.trip) == [
        "Cara left the trip",
        "Cara unlinked traveler Cara from account Cara",
    ]
    assert cara.get(crew.url("trip")).status_code == 404


def test_the_owner_cannot_leave(crew):
    response = crew.client("ann").post(crew.url("trip_leave"), follow=True)
    assert "The Owner cannot leave the trip. Make someone else the Owner first." in (
        response.content.decode()
    )
    assert TripMember.objects.filter(trip=crew.trip, user=crew.users["ann"]).exists()
    assert crew.client("sam").post(crew.url("trip_leave")).status_code == 404


# --- 6.5 Account menu and closing an account ----------------------------------------------------


def test_the_account_menu_shows_the_google_account(crew, settings):
    settings.GOOGLE_CLIENT_ID = "test-client"
    page = crew.client("sam").get(reverse("home")).content.decode()
    assert "Google account" in page and "Not linked" in page and "Close account" in page
    link_google(crew.users["sam"], "sam@example.com")
    page = crew.client("sam").get(reverse("home")).content.decode()
    assert "Linked: sam@example.com" in page


def close(client, username):
    return client.post(reverse("account_close"), {"username": username})


def test_closing_an_account(crew, make_user):
    cara = crew.users["cara"]
    cara.set_password(PASSWORD)
    cara.save()
    phone, laptop = Client(), Client()
    for device in (phone, laptop):
        device.post(reverse("login"), {"username": "cara", "password": PASSWORD})
    page = phone.get(reverse("account_close")).content.decode()
    assert (
        "Your account will be closed. You will be logged out and cannot log in until the admin "
        "restores the account." in page
    )
    assert "Close my account" in page and "Type “cara” to confirm." in page
    assert "Type “cara” to confirm." in close(phone, "carax").content.decode()
    response = close(phone, "CARA")
    assert response.status_code == 302 and response["Location"] == reverse("login")
    cara.refresh_from_db()
    assert not cara.is_active and cara.closed_at is not None
    assert not Session.objects.filter(session_key=laptop.session.session_key).exists()
    assert laptop.get(reverse("home")).status_code == 302  # Signed out everywhere.
    assert TripMember.objects.filter(user=cara).exists()  # Kept, so the admin can restore.
    assert crew.travelers["cara"].pk in {p.pk for p in cara.participations.all()}
    assert texts(crew.trip)[-1] == "Cara closed their account"
    people = crew.client("ann").get(crew.url("people")).content.decode()
    assert "Closed" in people
    summary = crew.client("ann").get(crew.url("summary")).content.decode()
    assert "Cara" in summary


def test_an_owner_cannot_close_while_others_are_in_the_trip(crew):
    ann = crew.client("ann")
    page = ann.get(reverse("account_close")).content.decode()
    assert "You are the Owner of Crew trip. Make someone else the Owner first." in page
    assert "Close my account" not in page and 'name="username"' not in page
    other = Trip.objects.create(name="Other trip", created_by=crew.users["ann"])
    TripMember.objects.create(trip=other, user=crew.users["ann"], role=TripMember.Role.OWNER)
    TripMember.objects.create(trip=other, user=crew.users["ben"])
    page = ann.get(reverse("account_close")).content.decode()
    assert "You are the Owner of Crew trip and Other trip. Make someone else" in page
    page = close(ann, "ann").content.decode()
    assert "You are the Owner of Crew trip and Other trip." in page
    assert User.objects.get(username="ann").is_active


def test_an_owner_alone_on_a_trip_may_close_and_their_invites_are_cancelled(crew):
    sam = crew.users["sam"]
    solo = Trip.objects.create(name="Solo trip", created_by=sam)
    TripMember.objects.create(trip=solo, user=sam, role=TripMember.Role.OWNER)
    client = crew.client("sam")
    client.post(
        reverse("invite_new", args=[solo.pk]),
        {"who": "gina@example.com", "traveler": "none", "confirm": "1"},
    )
    assert close(client, "sam").status_code == 302
    assert Invite.objects.get(trip=solo).state == Invite.State.CANCELLED
    assert Trip.objects.filter(pk=solo.pk).exists()
    assert [history.describe(e) for e in solo.history.order_by("id")][-2:] == [
        "Sam cancelled the invite for g***@example.com",
        "Sam closed their account",
    ]


def test_a_closed_account_sees_the_closed_message_and_axes_does_not_count_it(make_user, client):
    make_user("cara", is_active=False, closed_at=timezone.now())
    for _ in range(6):
        response = client.post(reverse("login"), {"username": "Cara", "password": PASSWORD})
        assert "This account is closed. Ask the admin to restore it." in response.content.decode()
    assert response.status_code == 200 and not AccessAttempt.objects.exists()
    wrong = client.post(reverse("login"), {"username": "cara", "password": "wrong"})
    assert "This account is closed" not in wrong.content.decode()
    assert AccessAttempt.objects.get().failures_since_start == 1
    assert "_auth_user_id" not in client.session


def test_a_closed_account_cannot_sign_in_with_google(client, google, crew):  # noqa: F811
    sam = crew.users["sam"]
    link_google(sam, "sam@example.com")
    User.objects.filter(pk=sam.pk).update(is_active=False, closed_at=timezone.now())
    google["email"] = "sam@example.com"
    page = sign_in_with_google(client).content.decode()
    assert "This account is closed. Ask the admin to restore it." in page
    assert "_auth_user_id" not in client.session


def test_admin_approve_skips_closed_accounts_and_restore_reopens_them(client, make_user):
    client.force_login(make_user("boss", is_staff=True, is_superuser=True))
    waiting = make_user("waiting", is_active=False)
    closed = make_user("closed_one", is_active=False, closed_at=timezone.now())
    url = reverse("admin:accounts_user_changelist")
    page = client.get(url).content.decode()
    assert "column-closed" in page
    client.post(url, {"action": "approve", "_selected_action": [waiting.pk, closed.pk]})
    waiting.refresh_from_db()
    closed.refresh_from_db()
    assert waiting.is_active and not closed.is_active
    client.post(url, {"action": "restore", "_selected_action": [closed.pk]})
    closed.refresh_from_db()
    assert closed.is_active and closed.closed_at is None
    login = Client().post(reverse("login"), {"username": "closed_one", "password": PASSWORD})
    assert login.status_code == 302


def test_closed_accounts_cannot_become_owner(crew):
    User.objects.filter(pk=crew.users["ben"].pk).update(is_active=False, closed_at=timezone.now())
    crew.client("ann").post(crew.url("member_transfer", crew.members["ben"].id))
    assert TripMember.objects.get(pk=crew.members["ann"].pk).is_owner


# --- 6.6 Email ----------------------------------------------------------------------------------


def test_the_invite_email(crew, email_on, settings):
    settings.TIME_ZONE = "Asia/Phnom_Penh"
    crew.trip.name = "Phnom <b>Penh</b>"
    crew.trip.save()
    users = User.objects.filter(pk=crew.users["ann"].pk)
    users.update(first_name="Ann <i>")
    link = invite_link(crew)
    message = email_on[0]
    assert message.subject == "Ann <i> invited you to Phnom <b>Penh</b> on Share Expense"
    expires = timezone.localtime(the_invite(crew).expires_at)
    day = f"{expires.day} {expires:%b} {expires.year} at {expires:%H:%M}"
    for text in (
        f"http://testserver{link}\nUse the Google account of gina@example.com.",
        f"This link works once and expires on {day} (Phnom Penh time).",
        "If you do not know Ann <i>, ignore this email.",
    ):
        assert text in message.body
    html, kind = message.alternatives[0]
    assert kind == "text/html"
    assert "Phnom &lt;b&gt;Penh&lt;/b&gt;" in html and "<b>Penh" not in html
    assert "Ann &lt;i&gt;" in html and f'href="http://testserver{link}"' in html


def test_email_not_configured(crew, settings):
    settings.EMAIL_HOST = ""
    mail.outbox.clear()
    page = post_invite(crew, "gina@example.com").content.decode()
    assert "Email sending is not set up. Copy the link and send it yourself." in page
    assert LINK.search(page) and Invite.objects.count() == 1 and not mail.outbox
    assert not InviteEmailAttempt.objects.exists()


def test_a_failed_send_keeps_the_invite(crew, email_on, monkeypatch):
    def fail(self, fail_silently=False):
        raise smtplib.SMTPException("down")

    monkeypatch.setattr(EmailMultiAlternatives, "send", fail)
    page = post_invite(crew, "gina@example.com").content.decode()
    assert "The email could not be sent. Copy the link and send it yourself." in page
    assert the_invite(crew).state == Invite.State.PENDING and LINK.search(page)
    assert InviteEmailAttempt.objects.count() == 1  # A failed attempt still counts.


def test_twenty_invite_emails_per_hour(crew, email_on):
    ann = crew.users["ann"]
    InviteEmailAttempt.objects.bulk_create(InviteEmailAttempt(sender=ann) for _ in range(19))
    old = InviteEmailAttempt.objects.create(sender=ann)
    InviteEmailAttempt.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(hours=2)
    )
    post_invite(crew, "one@example.com")  # 19 in the last hour: this is the 20th.
    assert len(email_on) == 1
    page = post_invite(crew, "two@example.com").content.decode()
    assert (
        "You have sent many invites in the last hour. Copy the link instead, or try again later."
        in page
    )
    assert len(email_on) == 1 and Invite.objects.count() == 2 and LINK.search(page)
    copy = crew.client("ann").post(crew.url("invite_copy", Invite.objects.last().pk), follow=True)
    assert LINK.search(copy.content.decode())  # Copies are never limited.


def test_no_sender_address_is_written_in_the_code():
    root = Path(__file__).resolve().parent.parent
    for folder in ("apps", "config", "templates"):
        for path in (root / folder).rglob("*"):
            if path.suffix in (".py", ".html", ".txt"):
                assert "monireach" not in path.read_text(), path


def test_the_email_settings_come_from_the_environment():
    source = (Path(__file__).resolve().parent.parent / "config" / "settings.py").read_text()
    for name in (
        "EMAIL_HOST",
        "EMAIL_PORT",
        "EMAIL_HOST_USER",
        "EMAIL_HOST_PASSWORD",
        "EMAIL_USE_SSL",
        "EMAIL_USE_TLS",
        "EMAIL_TIMEOUT",
        "DEFAULT_FROM_EMAIL",
    ):
        assert f'os.environ.get("{name}"' in source or f'env_bool("{name}"' in source, name


def test_a_new_traveler_keeps_the_name_the_owner_typed(crew, google):  # noqa: F811
    """The Owner's name for the new traveler wins over the person's Google name; the Google
    name is only the account's name."""
    link = invite_link(crew, "zoe@example.com", "new", new_name="XYZ")
    google["given_name"] = "Zoe"
    visitor = Client()
    visitor.get(link)
    accept_with_google(visitor, link, google, "zoe@example.com")
    member = TripMember.objects.get(trip=crew.trip, user__email__iexact="zoe@example.com")
    assert member.linked_traveler.name == "XYZ"
    assert member.user.display_name == "Zoe"


# The invite address checks (apps/trips/email_check.py).


def test_an_address_whose_domain_receives_no_email_is_refused(crew, monkeypatch):
    from apps.trips import email_check

    monkeypatch.setattr(email_check, "receives_email", lambda domain: domain != "gmial.con")
    page = post_invite(crew, "dan@gmial.con", confirm=False).content.decode()
    assert "No email can be delivered to gmial.con. Check the address." in page
    assert not Invite.objects.exists()


def test_a_typo_of_a_common_provider_is_offered_and_can_be_used(crew):
    page = post_invite(crew, "dan@gmial.com", confirm=False).content.decode()
    assert "Invite dan@gmial.com?" in page
    assert "Did you mean dan@gmail.com?" in page
    page = (
        crew.client("ann")
        .post(
            crew.url("invite_new"),
            {
                "who": "dan@gmial.com",
                "traveler": "none",
                "confirm": "1",
                "use_suggestion": "dan@gmail.com",
            },
        )
        .content.decode()
    )
    assert "Invite dan@gmail.com?" in page  # Asked again, with the corrected address.
    assert not Invite.objects.exists()  # Nothing is made until Confirm.


def test_the_typo_suggestion_can_be_ignored(crew):
    post_invite(crew, "dan@gmial.com")
    assert the_invite(crew).email == "dan@gmial.com"


def test_suggestion_rules():
    from apps.trips.email_check import suggestion

    assert suggestion("dan@gmial.com") == "dan@gmail.com"
    assert suggestion("dan@gmail.con") == "dan@gmail.com"
    assert suggestion("dan@hotmial.com") == "dan@hotmail.com"
    assert suggestion("dan@gmail.com") == ""
    assert suggestion("dan@company.org") == ""


@pytest.mark.real_email_check
def test_receives_email_reads_dns(monkeypatch):
    import dns.resolver

    from apps.trips import email_check

    class Record:
        def __init__(self, exchange):
            self.exchange = exchange

    answers = {
        ("mail.test", "MX"): [Record("mx.mail.test.")],
        ("web.test", "A"): ["192.0.2.1"],
        ("nullmx.test", "MX"): [Record(".")],
    }

    def resolve(self, domain, record):
        if domain == "missing.test":
            raise dns.resolver.NXDOMAIN
        if domain == "down.test":
            raise dns.resolver.LifetimeTimeout
        if (domain, record) in answers:
            return answers[(domain, record)]
        raise dns.resolver.NoAnswer

    monkeypatch.setattr(dns.resolver.Resolver, "resolve", resolve)
    email_check.receives_email.cache_clear()
    assert email_check.receives_email("mail.test")
    assert email_check.receives_email("web.test")  # No MX: mail goes to the address record.
    assert not email_check.receives_email("missing.test")
    assert not email_check.receives_email("nullmx.test")
    assert not email_check.receives_email("empty.test")
    assert email_check.receives_email("down.test")  # A DNS outage never blocks an invite.
    email_check.receives_email.cache_clear()
