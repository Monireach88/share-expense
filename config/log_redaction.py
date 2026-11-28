"""Invite tokens never reach the logs.

An invite link is /invite/<token>/ (old shared links: /join/<token>/); whoever reads the logs
could otherwise join the trip with it. ``redact`` replaces the token by "…". It is used by
gunicorn's access log (config/gunicorn_logger.py) and by Django's log handler (the
``RedactInviteTokens`` filter in config/settings.py), which logs the path of every 404, such as
an expired invite.
"""

import logging
import re

TOKEN_PATH = re.compile(r"/(invite|join)/[^/?#\s\"]+")


def redact(value):
    return TOKEN_PATH.sub(r"/\1/…", value) if isinstance(value, str) else value


class RedactInviteTokens(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, ()
        return True
