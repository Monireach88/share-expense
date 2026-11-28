from datetime import timedelta
from types import SimpleNamespace

from gunicorn.config import Config

from config.gunicorn_logger import RedactingLogger


def test_the_access_log_hides_invite_tokens_and_keeps_the_rest():
    logger = RedactingLogger(Config())
    environ = {
        "REQUEST_METHOD": "GET",
        "RAW_URI": "/invite/s3cr3t-T0ken_x/?a=1",
        "PATH_INFO": "/invite/s3cr3t-T0ken_x/",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "HTTP_REFERER": "https://example.com/invite/s3cr3t-T0ken_x/",
        "REMOTE_ADDR": "203.0.113.9",
    }
    resp = SimpleNamespace(status="200 OK", sent=10, headers=[])
    req = SimpleNamespace(headers=[("REFERER", environ["HTTP_REFERER"])])
    atoms = logger.atoms(resp, req, environ, timedelta(seconds=0))
    assert atoms["r"] == "GET /invite/…/?a=1 HTTP/1.1"
    assert atoms["U"] == "/invite/…/" and atoms["f"] == "https://example.com/invite/…/"
    assert "s3cr3t" not in repr(atoms)
    assert atoms["h"] == "203.0.113.9" and atoms["s"] == "200"
    other = dict(environ, RAW_URI="/trips/abc/", PATH_INFO="/trips/abc/", HTTP_REFERER="-")
    assert logger.atoms(resp, SimpleNamespace(headers=[]), other, timedelta(0))["r"] == (
        "GET /trips/abc/ HTTP/1.1"
    )


def test_django_log_lines_hide_invite_tokens():
    import logging

    from config.log_redaction import RedactInviteTokens

    record = logging.LogRecord(
        "django.request",
        logging.WARNING,
        __file__,
        1,
        "%s: %s",
        ("Not Found", "/invite/abc/"),
        None,
    )
    assert RedactInviteTokens().filter(record)
    assert record.getMessage() == "Not Found: /invite/…/"


def test_the_project_log_handler_uses_the_filter(settings):
    assert settings.LOGGING["handlers"]["console"]["filters"] == ["redact_invite_tokens"]
