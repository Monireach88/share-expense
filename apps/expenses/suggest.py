"""Writing suggestions for expense descriptions, from DeepSeek's chat API.

While a traveler types a description, the form asks for a cleaner version: correct spelling,
grammar and word choice, in the style of the trip's other descriptions ("Tuk-tuk to the market",
not "tuktuk 2 market"). The traveler sees it under the field and can accept it with one tap.

Without DEEPSEEK_API_KEY there are no suggestions and the form works as before. The text and up to
20 of the trip's earlier descriptions are sent to DeepSeek; nothing else about the trip is sent.
"""

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings
from django.core.cache import cache

from apps.trips.models import Trip

log = logging.getLogger(__name__)

API_URL = "https://api.deepseek.com/chat/completions"
TIMEOUT_SECONDS = 5
EXAMPLES = 20
# Each account may ask for this many suggestions per window, so a stuck page cannot run up costs.
LIMIT, WINDOW_SECONDS = 60, 600

SYSTEM_PROMPT = (
    "You edit short expense descriptions in a travel expense app. Rewrite the description with "
    "correct spelling, grammar, capital letters and word choice, in the same style as the "
    "trip's other descriptions (wording, length, capitalisation). Keep the meaning, every name, "
    "number and place, and the language of the description. Do not add facts. Reply with the "
    "description only: one line, no quotes, no full stop at the end, at most 200 characters."
)


def enabled() -> bool:
    return bool(settings.DEEPSEEK_API_KEY)


def allowed(user_id) -> bool:
    """Count this request against the account's limit; False when the limit is reached."""
    key = f"suggest:{user_id}"
    cache.add(key, 0, WINDOW_SECONDS)
    try:
        return cache.incr(key) <= LIMIT
    except ValueError:  # The counter expired between add and incr.
        return True


def examples(trip: Trip, exclude: str = "") -> list[str]:
    seen, result = set(), []
    for text in trip.expenses.exclude(description="").values_list("description", flat=True):
        key = text.casefold()
        if key not in seen and key != exclude.casefold():
            seen.add(key)
            result.append(text)
        if len(result) == EXAMPLES:
            break
    return result


def chat(messages: list[dict], *, max_tokens: int, json_output: bool = False) -> str:
    """One DeepSeek chat call; the answer text, or "" when the service fails."""
    body = {
        "model": settings.DEEPSEEK_MODEL,
        "messages": messages,
        "thinking": {"type": "disabled"},  # Short tasks need no reasoning, so it answers faster.
        "temperature": 0 if json_output else 0.2,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if json_output:
        body["response_format"] = {"type": "json_object"}
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return str(json.load(response)["choices"][0]["message"]["content"])
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError) as error:
        log.warning("DeepSeek call failed: %s", error)
        return ""


def suggest(trip: Trip, text: str) -> str:
    """A better wording of ``text``, or "" when there is none or the service fails."""
    text = " ".join(text.split())[:200]
    if not enabled() or len(text) < 3:
        return ""
    lines = "\n".join(f"- {e}" for e in examples(trip, exclude=text)) or "(none yet)"
    answer = chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Other descriptions in this trip:\n{lines}\n\nDescription: {text}",
            },
        ],
        max_tokens=80,
    )
    answer = " ".join(answer.split()).strip("\"'“”‘’ ").rstrip(".")[:200]
    # Nothing to offer when the text is already fine.
    return answer if answer and answer != text else ""
