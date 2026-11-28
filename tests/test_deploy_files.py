"""The production and staging compose files give each container only the variables it uses."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NOT_FOR_WEB = {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "CLOUDFLARE_TUNNEL_TOKEN"}


def example_names() -> set[str]:
    text = (ROOT / ".env.example").read_text()
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text, re.MULTILINE))


def web_names(compose: str) -> set[str]:
    web = compose.split("\n  web:\n", 1)[1].split("\n  postgres:\n", 1)[0]
    return set(re.findall(r"^      - ([A-Z][A-Z0-9_]*)$", web, re.MULTILINE))


@pytest.mark.parametrize("name", ["prod", "staging"])
def test_web_gets_every_app_variable_and_no_other_secret(name):
    compose = (ROOT / f"docker-compose.{name}.yml").read_text()
    assert web_names(compose) == example_names() - NOT_FOR_WEB
    assert "env_file" not in compose  # Every container lists its own variables.
    assert compose.count('max-size: "10m"') == 3  # Log rotation on all three services.
