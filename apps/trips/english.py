"""English copies of text people write (spec_languages.md section 3).

A text with Khmer or Chinese letters gets a stored English copy, so a reader in English sees
English. Text without those letters is already English, and its copy stays empty. The copy comes
from the person (the form's "English" box) or, when it is empty, from DeepSeek (the same client
and daily limit as the other AI features, apps/expenses/suggest.py).
"""

import re

from django.utils.translation import get_language, pgettext_lazy
from django.utils.translation import gettext_lazy as _

from apps.expenses import suggest

# Khmer (U+1780-17FF, U+19E0-19FF) and Han characters (CJK Unified Ideographs, Extension A).
NEEDS_COPY = re.compile("[ក-៿᧠-᧿㐀-䶿一-鿿]")
# The same pattern for the browser; keep the two in step (static/js/english_copy.js).
NEEDS_COPY_JS = r"[ក-៿᧠-᧿㐀-䶿一-鿿]"

WRITE_ENGLISH = _("Write the English version.")
# The label of the "English" box under a text (not the name of a language in a menu).
ENGLISH_LABEL = pgettext_lazy(
    "label of the box with the English translation of the text above", "English"
)

PROMPT = (
    "You translate short texts from a travel expense app into English. Give a short, natural "
    "English translation of the text. Keep every name, number and currency code unchanged. Reply "
    "with the translation only: no quotes, no explanation."
)


def needs_copy(text) -> bool:
    return bool(NEEDS_COPY.search(text or ""))


def in_english() -> bool:
    return (get_language() or "").split("-")[0] == "en"


def shown(obj, field: str) -> str:
    """The text to show a reader: in English the English copy when there is one, otherwise (and
    in every other language) the text as it was written."""
    original = getattr(obj, field)
    if in_english():
        return getattr(obj, f"{field}_en", "") or original
    return original


def translate(text: str, user_id, max_length: int = 200) -> str:
    """An English copy of ``text`` from DeepSeek, or "" when the service is off, fails, or the
    account or daily limit is reached (the request counts against both)."""
    if not suggest.enabled() or not suggest.allowed(user_id):
        return ""
    return ask(text, max_length)


def ask(text: str, max_length: int = 200) -> str:
    """The DeepSeek call alone, for a caller that has counted the request itself."""
    text = " ".join(text.split())
    if not text or not suggest.enabled():
        return ""
    answer = suggest.chat(
        [{"role": "system", "content": PROMPT}, {"role": "user", "content": text}],
        max_tokens=max(120, max_length),
    )
    return " ".join(answer.split()).strip("\"'“”‘’ ")[:max_length]


def copy_for(text: str, typed: str, user_id, *, max_length: int, keep: str = "") -> str | None:
    """The English copy to store for ``text``.

    ``typed`` is what the person has in the English box. "" means no copy is needed. None means
    one is needed but could not be made (the caller shows WRITE_ENGLISH). ``keep`` is the copy
    stored before an edit: when the text changed and ``typed`` is still ``keep``, the old copy
    no longer fits, so a new one is made.
    """
    if not needs_copy(text):
        return ""
    typed = " ".join((typed or "").split())
    if typed and typed != keep:
        return typed[:max_length]
    return translate(text, user_id, max_length) or None


class EnglishCopyMixin:
    """A ModelForm mixin: for each ``english_fields`` pair {"text field": "English field"} it
    keeps the English field empty for English text and fills it (from the person, else from
    DeepSeek) for Khmer or Chinese text. A copy that cannot be made is the form error
    WRITE_ENGLISH on the English field. Put the mixin before ModelForm; pass ``user=`` (the
    account that is saving; its AI limit is used)."""

    english_fields: dict[str, str] = {}

    def __init__(self, *args, user=None, **kwargs):
        self.copy_user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        editing = not self.instance._state.adding
        for source, target in self.english_fields.items():
            if source in self.errors or target in self.errors:
                continue
            text = cleaned.get(source) or ""
            changed = editing and text != (self.initial.get(source) or "")
            copy = copy_for(
                text,
                cleaned.get(target, ""),
                getattr(self.copy_user, "pk", None),
                max_length=self._meta.model._meta.get_field(target).max_length,
                keep=(self.initial.get(target) or "") if changed else "",
            )
            if copy is None:
                self.add_error(target, WRITE_ENGLISH)
            else:
                cleaned[target] = copy
        return cleaned
