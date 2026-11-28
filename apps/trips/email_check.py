"""Two checks on an invite address before the invite is made.

No server says whether a mailbox exists (mail providers refuse, so spammers cannot collect
addresses), so the app checks only what can be checked: whether the part after "@" receives
email at all, and whether it looks like a typo of a common provider ("gmial.com").
"""

import difflib
from functools import lru_cache

import dns.exception
import dns.resolver

COMMON_DOMAINS = (
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "live.com",
    "icloud.com",
    "me.com",
    "proton.me",
    "protonmail.com",
    "zoho.com",
    "aol.com",
)


@lru_cache(maxsize=256)
def receives_email(domain: str) -> bool:
    """False only when DNS answers that the domain has no mail server: no MX record and no
    address record (mail falls back to the address record, RFC 5321 section 5.1). Any other
    DNS trouble (timeout, server failure) gives True, so a DNS outage never blocks an invite."""
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 4
    for record in ("MX", "A", "AAAA"):
        try:
            answer = resolver.resolve(domain, record)
        except dns.resolver.NXDOMAIN:
            return False  # The domain does not exist at all.
        except dns.resolver.NoAnswer:
            continue
        except dns.exception.DNSException:
            return True
        # A "null MX" (RFC 7505) means the domain says it accepts no email.
        return not (record == "MX" and all(str(r.exchange) == "." for r in answer))
    return False


def suggestion(email: str) -> str:
    """The address with a common provider's domain when the typed domain looks like a typo of
    it ("dan@gmial.com" -> "dan@gmail.com"), else ""."""
    name, _, domain = email.rpartition("@")
    if not name or domain in COMMON_DOMAINS:
        return ""
    match = difflib.get_close_matches(domain, COMMON_DOMAINS, n=1, cutoff=0.8)
    return f"{name}@{match[0]}" if match else ""
