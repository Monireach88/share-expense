"""Personal invites (spec sections 6.2, 6.3 and 6.6): make, renew, cancel, expire and accept one,
and send its email.

A link holds a random token; only its SHA-256 hash is stored. Every change runs in one
transaction under the trip lock and writes its History entry there. History shows the address
partly hidden ("d***@example.com"), because every member can read History.
"""

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta

from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError, transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.disputes import rules as disputes
from apps.disputes.models import Notification

from . import history
from .access import lock_trip
from .models import Invite, InviteEmailAttempt, Participant, Trip, TripMember

logger = logging.getLogger(__name__)

LIFETIME = timedelta(days=7)
EMAILS_PER_HOUR = 20


class InviteRefused(Exception):
    """The invite cannot be used; the message says why, in words for the person."""


# --- Tokens and addresses -----------------------------------------------------------------------


def new_token() -> str:
    """32 random bytes, URL-safe (43 characters)."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def mask(email: str) -> str:
    """ "dan@example.com" -> "d***@example.com": what History and strangers see."""
    name, _at, domain = email.partition("@")
    return f"{name[:1]}***@{domain}"


def find_by_token(token: str) -> Invite | None:
    if not token:
        return None
    return Invite.objects.select_related("trip").filter(token_hash=token_hash(token)).first()


def link_for(request, token: str) -> str:
    return request.build_absolute_uri(reverse("invite", args=[token]))


def google_email(user) -> str:
    """The address of the Google account linked to ``user``, as Google last sent it, or ""."""
    account = SocialAccount.objects.filter(user=user, provider="google").first()
    return (account.extra_data.get("email") or "") if account else ""


def google_user(email: str):
    """The approved, not closed account that signs in with Google as ``email``, or None."""
    account = (
        SocialAccount.objects.select_related("user")
        .filter(
            provider="google",
            extra_data__email__iexact=email,
            user__is_active=True,
            user__closed_at__isnull=True,
        )
        .first()
    )
    return account.user if account else None


def expiry_text(invite: Invite) -> str:
    """When the link stops working, in the app's time zone: "5 Dec 2026 at 00:16"."""
    when = timezone.localtime(invite.expires_at)
    return _("%(day)s at %(time)s") % {
        "day": f"{when.day} {when:%b} {when.year}",
        "time": f"{when:%H:%M}",
    }


def time_zone_city() -> str:
    """The city of the app's time zone, for the email: "Asia/Phnom_Penh" -> "Phnom Penh"."""
    return settings.TIME_ZONE.rsplit("/", 1)[-1].replace("_", " ")


def is_expired(invite: Invite) -> bool:
    return invite.state == Invite.State.EXPIRED or invite.expires_at <= timezone.now()


def open_invites(trip: Trip):
    return trip.invites.filter(state__in=Invite.OPEN_STATES).select_related("traveler")


# --- The Owner's actions ------------------------------------------------------------------------


def _history_values(invite: Invite) -> dict:
    return {"traveler": invite.traveler_label}


def create(
    trip: Trip,
    email: str,
    *,
    by: TripMember,
    traveler: Participant | None = None,
    new_traveler_name: str = "",
) -> tuple[Invite, str]:
    """Make a personal invite; returns it and its token. The caller has checked the form."""
    token = new_token()
    with transaction.atomic():
        trip = lock_trip(trip)
        invite = Invite.objects.create(
            trip=trip,
            email=email.strip().lower(),
            traveler=traveler,
            traveler_name=traveler.name if traveler else "",
            new_traveler_name=new_traveler_name,
            token_hash=token_hash(token),
            invited_by=by.user,
            invited_by_name=by.user.display_name,
            expires_at=timezone.now() + LIFETIME,
        )
        history.record(
            trip,
            by,
            "invited",
            "invite",
            object_id=invite.pk,
            label=mask(invite.email),
            values=_history_values(invite),
        )
    return invite, token


def renew(invite: Invite, *, by: TripMember, again: bool) -> str:
    """A new token and 7 more days, for Copy link and Send again; the old link stops working.
    Works on an expired invite too. Only Send again (``again``) is recorded in History."""
    token = new_token()
    with transaction.atomic():
        lock_trip(invite.trip)
        invite = Invite.objects.select_for_update().get(pk=invite.pk)
        if not invite.is_open:
            raise InviteRefused(_("This invite was already used or cancelled."))
        invite.token_hash = token_hash(token)
        invite.state = Invite.State.PENDING
        invite.expires_at = timezone.now() + LIFETIME
        invite.save(update_fields=["token_hash", "state", "expires_at"])
        if again:
            history.record(
                invite.trip,
                by,
                "sent_again",
                "invite",
                object_id=invite.pk,
                label=mask(invite.email),
            )
    return token


def cancel(invite: Invite, *, by) -> None:
    with transaction.atomic():
        lock_trip(invite.trip)
        invite = Invite.objects.select_for_update().get(pk=invite.pk)
        if not invite.is_open:
            return
        invite.state = Invite.State.CANCELLED
        invite.cancelled_at = timezone.now()
        invite.save(update_fields=["state", "cancelled_at"])
        history.record(
            invite.trip, by, "cancelled", "invite", object_id=invite.pk, label=mask(invite.email)
        )


def cancel_owned_by(user) -> None:
    """An Owner who closes their account cancels their trips' open invites (section 6.2)."""
    trips = TripMember.objects.filter(user=user, role=TripMember.Role.OWNER).values("trip_id")
    for invite in Invite.objects.filter(trip_id__in=trips, state__in=Invite.OPEN_STATES):
        cancel(invite, by=user)


# --- Opening and accepting ----------------------------------------------------------------------


def is_live(invite: Invite | None) -> bool:
    return (
        invite is not None
        and invite.state == Invite.State.PENDING
        and invite.expires_at > timezone.now()
    )


def expire_if_due(invite: Invite) -> None:
    """Record the expiry once, when someone opens the expired link (no timer does it)."""
    if invite.state != Invite.State.PENDING or invite.expires_at > timezone.now():
        return
    with transaction.atomic():
        lock_trip(invite.trip)
        fresh = Invite.objects.select_for_update().get(pk=invite.pk)
        if fresh.state != Invite.State.PENDING or fresh.expires_at > timezone.now():
            return
        fresh.state = Invite.State.EXPIRED
        fresh.save(update_fields=["state"])
        history.record(
            fresh.trip, None, "expired", "invite", object_id=fresh.pk, label=mask(fresh.email)
        )
    invite.state = Invite.State.EXPIRED


def accept(invite: Invite, token: str, user) -> Trip:
    """Make ``user`` a Member of the invite's trip, linked to the invited traveler when it is still
    free; otherwise view only, and the Owner is told to link the right traveler (section 6.3).

    The caller has checked that ``user`` proved the invited address with Google.
    """
    with transaction.atomic():
        trip = lock_trip(invite.trip)
        invite = Invite.objects.select_for_update().get(pk=invite.pk)
        if invite.token_hash != token_hash(token) or not is_live(invite):
            raise InviteRefused(
                _("This invite no longer works. Ask the Owner of the trip for a new one.")
            )
        if user.is_closed:
            raise InviteRefused(_("This account is closed. Ask the admin to restore it."))
        if TripMember.objects.filter(trip=trip, user=user).exists():
            return trip
        traveler, created = _invited_traveler(trip, invite, user)
        member = TripMember.objects.create(trip=trip, user=user)
        invite.state = Invite.State.ACCEPTED
        invite.accepted_at = timezone.now()
        invite.accepted_by = user
        invite.save(update_fields=["state", "accepted_at", "accepted_by"])
        if created:
            # The Owner chose the new traveler; it is recorded as theirs.
            history.record(
                trip,
                invite.invited_by,
                "added",
                "traveler",
                object_id=traveler.pk,
                label=traveler.name,
            )
        history.record(
            trip,
            user,
            "accepted",
            "invite",
            object_id=invite.pk,
            label=mask(invite.email),
            values={"traveler": traveler.name if traveler else "", "member_id": member.pk},
        )
        owner = trip.memberships.get(role=TripMember.Role.OWNER).user_id
        people = reverse("people", args=[trip.pk])
        disputes.notify(
            trip, {owner}, Notification.Kind.INVITE_ACCEPTED, by=user, label=trip.name, link=people
        )
        if traveler is None and invite.traveler_label:
            disputes.notify(
                trip,
                {owner},
                Notification.Kind.INVITE_UNLINKED,
                by=user,
                label=trip.name,
                detail=invite.traveler_label,
                link=people,
            )
    return trip


def _invited_traveler(trip: Trip, invite: Invite, user) -> tuple[Participant | None, bool]:
    """The traveler to link, and whether it was made now. None when the invited traveler got an
    account or was removed meanwhile, or a new one can no longer be made (trip settled since, or
    the name taken)."""
    if invite.new_traveler_name:
        name = invite.new_traveler_name
        if trip.is_settled or trip.participants.filter(name__iexact=name).exists():
            return None, False
        return Participant.objects.create(trip=trip, name=name, user=user), True
    if invite.traveler_id is None:
        return None, False
    traveler = Participant.objects.select_for_update().filter(pk=invite.traveler_id).first()
    if traveler is None or traveler.user_id is not None:
        return None, False
    traveler.user = user
    try:
        with transaction.atomic():
            traveler.save(update_fields=["user"])
    except IntegrityError:  # The account is linked to another traveler here already.
        return None, False
    return traveler, False


# --- Email (section 6.6) ------------------------------------------------------------------------


@dataclass
class Outcome:
    """What happened to the invite email; ``message`` is shown to the Owner."""

    sent: bool
    message: str


def email_configured() -> bool:
    return bool(settings.EMAIL_HOST)


def send_email(invite: Invite, link: str, sender) -> Outcome:
    """Send the invite email, unless email is not set up or ``sender`` reached the hourly limit.
    A failed send never loses the invite; the Owner copies the link instead."""
    if not email_configured():
        return Outcome(False, _("Email sending is not set up. Copy the link and send it yourself."))
    since = timezone.now() - timedelta(hours=1)
    if (
        InviteEmailAttempt.objects.filter(sender=sender, created_at__gte=since).count()
        >= EMAILS_PER_HOUR
    ):
        return Outcome(
            False,
            _(
                "You have sent many invites in the last hour. Copy the link instead, or try "
                "again later."
            ),
        )
    InviteEmailAttempt.objects.create(sender=sender)
    context = {
        "inviter": sender.display_name,
        "trip": invite.trip.name,
        "link": link,
        "address": invite.email,
        "expires": expiry_text(invite),
        "city": time_zone_city(),
    }
    message = EmailMultiAlternatives(
        subject=render_to_string("trips/email/invite_subject.txt", context).strip(),
        body=render_to_string("trips/email/invite.txt", context),
        to=[invite.email],
    )
    message.attach_alternative(render_to_string("trips/email/invite.html", context), "text/html")
    try:
        message.send()
    except Exception:  # SMTP errors, timeouts, refused connections: the link still works.
        logger.exception("The invite email could not be sent")
        return Outcome(False, _("The email could not be sent. Copy the link and send it yourself."))
    Invite.objects.filter(pk=invite.pk).update(sent_at=timezone.now())
    return Outcome(True, _("The invite email was sent to %(email)s.") % {"email": invite.email})
