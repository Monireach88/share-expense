"""Usernames: a-z, 0-9 and _, 3 to 30 characters, stored in lowercase (spec section 6.1).

Every way an account is created goes through these helpers: the sign-up form and the admin
(through the model's validator and ``User.clean``), ``User.save`` (so nothing reaches the
database in capitals) and Google sign-in (``generate_username``).
"""

import re
import unicodedata

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

USERNAME_RE = re.compile(r"[A-Za-z0-9_]{3,30}")
MAX_LENGTH = 30
TAKEN = _("This username is taken.")
BAD = _("Use only the characters listed above.")


def validate_username(value: str) -> None:
    """Capitals are accepted here because they are lowercased on save ("Maly" is "maly")."""
    if not USERNAME_RE.fullmatch(value or ""):
        raise ValidationError(BAD, code="invalid_username")


def axes_username(request, credentials) -> str | None:
    """The name django-axes counts failed logins under, so "Maly" and "maly" share one lock."""
    source = credentials if credentials else getattr(request, "POST", {})
    name = source.get("username")
    return name.strip().lower() if isinstance(name, str) else name


def generate_username(texts, taken) -> str:
    """A free username from names, an email or a word: the email name first, else the first text.

    ``taken`` answers "is this username used?". A number is added when the name is taken.
    """
    texts = [t for t in texts if t]
    texts.sort(key=lambda t: "@" not in t)  # An email name first (stable for the others).
    for text in texts:
        base = text.split("@")[0]
        base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode().lower()
        base = re.sub(r"[^a-z0-9_]", "", base)[:MAX_LENGTH]
        if len(base) >= 3:
            break
    else:
        base = "user"
    candidate, number = base, 1
    while taken(candidate):
        number += 1
        suffix = str(number)
        candidate = base[: MAX_LENGTH - len(suffix)] + suffix
    return candidate
