"""gunicorn's access log without invite tokens (scripts/start.sh uses this logger class).

Every logged value (the request line, the path, the Referer header) goes through
``config.log_redaction.redact``; the rest of the access log stays as it was.
"""

from gunicorn.glogging import Logger

from config.log_redaction import redact


class RedactingLogger(Logger):
    def atoms(self, resp, req, environ, request_time):
        return {
            key: redact(value)
            for key, value in super().atoms(resp, req, environ, request_time).items()
        }
