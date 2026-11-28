"""Currencies offered in forms. Any ISO 4217 code works in the database; this list only feeds the dropdowns.

The common currencies of the app's trips come first, then the main currency of every other
country (country_currency.py) in alphabetical order, so a suggested currency is always a choice.
"""

from .country_currency import COUNTRY_CURRENCY

COMMON = [
    "USD",
    "KHR",
    "VND",
    "THB",
    "LAK",
    "MYR",
    "SGD",
    "IDR",
    "PHP",
    "CNY",
    "HKD",
    "TWD",
    "JPY",
    "KRW",
    "INR",
    "AUD",
    "NZD",
    "EUR",
    "GBP",
]
CURRENCIES = [*COMMON, *sorted(set(COUNTRY_CURRENCY.values()) - set(COMMON))]
CURRENCY_CHOICES = [(code, code) for code in CURRENCIES]
DEFAULT_CURRENCY = "USD"
