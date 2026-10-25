"""Currencies offered in forms. Any ISO 4217 code works in the database; this list only feeds the dropdowns."""

CURRENCIES = [
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
CURRENCY_CHOICES = [(code, code) for code in CURRENCIES]
DEFAULT_CURRENCY = "USD"
