"""Template helpers for the UI: money formatting, icons and expense-type emoji."""

from decimal import Decimal

from django import template
from django.templatetags.static import static
from django.utils.html import format_html

register = template.Library()

# Currencies people pay in whole units. Cents still show if an amount has them.
WHOLE_UNIT_CURRENCIES = {"VND", "KHR", "JPY", "KRW", "IDR", "LAK"}

TYPE_EMOJI = {
    "transport": "🚕",
    "accommodation": "🏨",
    "food": "🍜",
    "medical": "💊",
    "translation": "💬",
    "shopping": "🛍️",
    "activities": "🎟️",
    "other": "📦",
}


def format_amount(amount, currency: str = "") -> str:
    """600000 VND -> "600,000"; 42.5 USD -> "42.50"."""
    if amount is None or amount == "":
        return ""
    value = Decimal(str(amount))
    if currency in WHOLE_UNIT_CURRENCIES and value == value.to_integral_value():
        return f"{value:,.0f}"
    return f"{value:,.2f}"


@register.filter
def amount(value, currency=""):
    """The number only, for places where the currency is shown once, e.g. a column."""
    return format_amount(abs(value) if isinstance(value, Decimal) else value, currency)


@register.filter
def money(value, currency):
    """Number plus a muted currency code: 600,000 VND."""
    if value is None:
        return ""
    if isinstance(value, Decimal):
        value = abs(value)  # The sign is shown by the words around it ("owes", "is owed").
    return format_html('{} <span class="cur">{}</span>', format_amount(value, currency), currency)


@register.simple_tag
def icon(name: str, css: str = "icon"):
    return format_html(
        '<svg class="{}" aria-hidden="true"><use href="{}#{}"></use></svg>',
        css,
        static("img/icons.svg"),
        name,
    )


@register.filter
def type_emoji(category: str) -> str:
    return TYPE_EMOJI.get(category, "📦")


@register.filter
def signed(value, currency=""):
    """+120.00 when the group owes the person, −45.00 when the person owes the group."""
    if value is None:
        return ""
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return f"{sign}{format_amount(abs(value), currency)}"


@register.filter
def keep_hyphens(text):
    """Keep "check-up" on one line: a line may break between words, never inside one.

    The text a person copies stays the same; only the line breaking changes.
    """
    from django.utils.html import escape
    from django.utils.safestring import mark_safe

    words = escape(str(text)).split(" ")
    return mark_safe(" ".join(f'<span class="nowrap">{w}</span>' if "-" in w else w for w in words))
