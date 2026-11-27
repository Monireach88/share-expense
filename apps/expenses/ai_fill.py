"""Add an expense from one sentence ("Maly bought drinks for Maly and Sophorn, 40000 VND").

DeepSeek only copies what the sentence states, as JSON, and never guesses. This module then
checks every value against the trip itself: a name must match exactly one traveler, the currency
must have a rate in the trip, the type must be one of the trip's types. Anything missing or
unclear is reported, so the form is filled only with what is certain. Nothing is saved here:
the traveler checks the form and presses Save.
"""

import json
from datetime import date
from decimal import Decimal, InvalidOperation

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.trips.models import Participant, Trip

from . import suggest

MAX_CHARS = 300

PROMPT = """You read one short note about money spent on a trip and return json.
Copy only what the note clearly states. Never guess, never invent, never fill a gap.
When the note does not clearly state something, use null (or [] for lists).

Return exactly these keys, like this example:
{{"is_expense": true, "amount": "40000", "currency": "VND", "payer": "Maly",
"beneficiaries": ["Maly", "Sophorn"], "everyone": false, "type": "Food & drink",
"description": "Drinks", "date": "2026-11-25"}}

Rules:
- is_expense: false when the note is not about something someone paid for.
- amount: the number as written in the note, without thousands separators; no conversion.
- currency: a 3-letter code, only when the note names the currency or uses a clear sign
  (₫ = VND, ៛ = KHR, $ = USD, ฿ = THB).
- payer: the person who paid, written as in the note. "I" or "me" means {me}.
- beneficiaries: the people it was for, written as in the note. "I" or "me" means {me}.
  "everyone", "all of us", "the whole group": everyone true and beneficiaries [].
- type: one of {types}, only when the item clearly belongs to it.
- description: the item or service, short, with a capital first letter ("Drinks", "Taxi to
  the airport"). Do not put names, amounts or dates in it.
- date: YYYY-MM-DD, only when the note names a month, a weekday or a word such as "today" or
  "yesterday" ("Nov 25", "25/11", "on Monday"). A bare number ("dinner 25") is never a date.
  Today is {today}. A day without a year is in {year}.
- A bare number with no currency is the amount only when it is the only number; its currency
  stays null.

Travelers on this trip: {travelers}."""


def match_traveler(name: str, travelers: list[Participant]) -> Participant | None:
    """The one traveler a name means: the full name, or words that fit exactly one traveler
    ("Maly" for "HENG MALY"). None when no traveler or several travelers fit."""
    words = name.casefold().split()
    if not words:
        return None
    exact = [p for p in travelers if p.name.casefold() == " ".join(words)]
    if len(exact) == 1:
        return exact[0]
    fits = [p for p in travelers if set(words) <= set(p.name.casefold().split())]
    return fits[0] if len(fits) == 1 else None


def _amount(value) -> Decimal | None:
    try:
        amount = Decimal(str(value).replace(",", "").replace(" ", ""))
    except InvalidOperation, ValueError:
        return None
    return amount if amount > 0 else None


def fill(trip: Trip, text: str, me: Participant | None) -> dict:
    """The form values the note states for certain, and what is still missing.

    Returns {"fields": {...}, "missing": [...]} or {"error": "..."}.
    """
    text = " ".join(text.split())[:MAX_CHARS]
    if len(text) < 5:
        return {"error": _("Describe the expense in a sentence.")}
    travelers = list(trip.participants.all())
    types = {c.name.casefold(): c for c in trip.categories.all()}
    today = timezone.localdate()
    prompt = PROMPT.format(
        me=me.name if me else "nobody (the writer is not a traveler)",
        types=", ".join(c.name for c in types.values()),
        today=today.isoformat(),
        year=today.year,
        travelers=", ".join(p.name for p in travelers),
    )
    answer = suggest.chat(
        [{"role": "system", "content": prompt}, {"role": "user", "content": text}],
        max_tokens=300,
        json_output=True,
    )
    try:
        data = json.loads(answer)
    except ValueError:
        return {"error": _("The text could not be read. Try again.")}
    if not isinstance(data, dict):
        return {"error": _("The text could not be read. Try again.")}
    if data.get("is_expense") is False:
        return {"error": _("This box only adds expenses.")}

    fields: dict = {}
    missing: list[str] = []

    amount = _amount(data.get("amount"))
    if amount is None:
        missing.append(_("the amount"))
    else:
        fields["amount"] = f"{amount:f}"

    currency = str(data.get("currency") or "").upper()
    if not currency:
        missing.append(_("the currency"))
    elif currency not in trip.currencies():
        missing.append(
            _("the currency (%(code)s has no exchange rate in this trip)") % {"code": currency}
        )
    else:
        fields["currency"] = currency

    payer_name = str(data.get("payer") or "").strip()
    payer = match_traveler(payer_name, travelers) if payer_name else None
    if payer:
        fields["payer"] = str(payer.id)
    elif payer_name:
        missing.append(
            _("who paid (no single traveler is called “%(name)s”)") % {"name": payer_name}
        )
    else:
        missing.append(_("who paid"))

    if data.get("everyone") is True:
        fields["beneficiaries"] = [str(p.id) for p in travelers]
    else:
        names = [str(n).strip() for n in data.get("beneficiaries") or [] if str(n).strip()]
        found, unknown = [], []
        for name in names:
            person = match_traveler(name, travelers)
            (found if person else unknown).append(person or name)
        if unknown:
            missing.append(
                _("who it was for (no single traveler is called %(names)s)")
                % {"names": ", ".join(f"“{n}”" for n in unknown)}
            )
        elif found:
            fields["beneficiaries"] = list(dict.fromkeys(str(p.id) for p in found))
        else:
            missing.append(_("who it was for"))

    category = types.get(str(data.get("type") or "").casefold())
    if category:
        fields["category"] = str(category.pk)
    else:
        missing.append(_("the type"))

    description = " ".join(str(data.get("description") or "").split())[:200]
    if description:
        fields["description"] = description
    else:
        missing.append(_("what was bought"))

    day = today
    if data.get("date"):
        try:
            day = date.fromisoformat(str(data["date"]))
        except ValueError:
            day = today
    fields["date"] = day.isoformat()

    return {"fields": fields, "missing": missing}
