"""Market exchange rates, to suggest a rate when a trip gets a new currency.

The rates come from ExchangeRate-API's open endpoint (https://open.er-api.com, no key; its
terms ask for a visible "Rates by ExchangeRate-API" link next to the rates shown). The server
asks, never the browser, so the Content-Security-Policy keeps connect-src 'self'. One answer per
base currency per day is kept in the database cache, because the service updates once a day.

Without EXCHANGE_RATES_URL there are no market rates; the suggested currency still works.
"""

import json
import logging
import urllib.error
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 4
DAY_SECONDS = 24 * 60 * 60
# A failed call is remembered this long, so a service outage does not slow every page by 4 s.
FAILURE_SECONDS = 5 * 60
# Each account may ask for this many suggestions per window.
LIMIT, WINDOW_SECONDS = 60, 600


@dataclass(frozen=True)
class MarketRate:
    rate: Decimal  # 1 base = ``rate`` currency, rounded for display (see ``rounded``).
    day: date  # The day the service last updated its rates.


def enabled() -> bool:
    return bool(settings.EXCHANGE_RATES_URL)


def allowed(user_id) -> bool:
    """Count this request against the account's limit; False when it is reached."""
    key = f"rates:ask:{user_id}"
    cache.add(key, 0, WINDOW_SECONDS)
    try:
        return cache.incr(key) <= LIMIT
    except ValueError:  # The counter expired between add and incr.
        return True


def _fetch(base: str) -> dict | None:
    """The service's answer for ``base``: {"rates": {...}, "day": "YYYY-MM-DD"}, or None."""
    url = f"{settings.EXCHANGE_RATES_URL.rstrip('/')}/{base}"
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            data = json.load(response)
        if data.get("result") != "success" or not isinstance(data.get("rates"), dict):
            raise ValueError(f"result {data.get('result')!r}")
        day = parsedate_to_datetime(data["time_last_update_utc"]).date()
        rates = {str(k): str(v) for k, v in data["rates"].items()}
    except (urllib.error.URLError, TimeoutError, OSError, KeyError, TypeError, ValueError) as error:
        log.warning("Exchange rate call for %s failed: %s", base, error)
        return None
    return {"rates": rates, "day": day.isoformat()}


def latest(base: str) -> dict | None:
    """Today's rates for ``base`` from the cache, or from the service once a day."""
    if not enabled():
        return None
    key = f"rates:{base}:{timezone.localdate().isoformat()}"
    answer = cache.get(key)
    if answer is None:
        answer = _fetch(base) or {}
        cache.set(key, answer, DAY_SECONDS if answer else FAILURE_SECONDS)
    return answer or None


def rounded(rate: Decimal) -> Decimal:
    """The rate as the form shows it: whole for 100 or more ("4068"), two decimals from 1 to
    100 ("33.93"), four significant digits below 1 ("0.8621", "0.000246"; at most 6 decimals,
    the database's limit)."""
    if rate >= 100:
        return rate.quantize(Decimal(1), ROUND_HALF_UP)
    if rate >= 1:
        return rate.quantize(Decimal("0.01"), ROUND_HALF_UP)
    places = min(6, 4 - rate.adjusted() - 1)
    return rate.quantize(Decimal(1).scaleb(-places), ROUND_HALF_UP)


def market_rate(base: str, currency: str) -> MarketRate | None:
    """1 ``base`` = how many ``currency`` today, or None when unknown or the service fails."""
    answer = latest(base)
    if not answer or currency not in answer["rates"]:
        return None
    try:
        rate = rounded(Decimal(answer["rates"][currency]))
    except InvalidOperation:
        return None
    if rate <= 0:
        return None
    return MarketRate(rate=rate, day=date.fromisoformat(answer["day"]))
