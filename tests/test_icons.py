"""Favicon, home-screen icons and the web app manifest."""

import re

from django.contrib.staticfiles import finders
from django.urls import reverse


def head_links(html: str) -> dict[str, str]:
    """rel (plus sizes, if any) -> href of every <link> in the page head."""
    head = html.split("</head>", 1)[0]
    links = {}
    for tag in re.findall(r"<link [^>]+>", head):
        rel = re.search(r'rel="([^"]+)"', tag).group(1)
        sizes = re.search(r'sizes="([^"]+)"', tag)
        kind = re.search(r'type="([^"]+)"', tag)
        key = rel + (f" {sizes.group(1)}" if sizes else "") + (f" {kind.group(1)}" if kind else "")
        links[key] = re.search(r'href="([^"]+)"', tag).group(1)
    return links


def static_file(url: str):
    return finders.find(url.split("/static/", 1)[1])


def test_every_page_links_the_icons_and_they_exist(client):
    links = head_links(client.get(reverse("login")).content.decode())
    for key in ("icon image/svg+xml", "icon 32x32 image/png", "apple-touch-icon"):
        assert static_file(links[key]), key
    assert client.get(links["manifest"]).status_code == 200


def test_static_icons_are_served(live_server):
    import urllib.request

    for name in ("favicon.svg", "favicon-32.png", "apple-touch-icon.png", "icon-192.png"):
        with urllib.request.urlopen(f"{live_server.url}/static/img/{name}") as response:
            assert response.status == 200


def test_manifest_lists_the_app_icons(client):
    response = client.get(reverse("web_manifest"))
    assert response["Content-Type"] == "application/manifest+json"
    data = response.json()
    assert data["name"] == "Share Expense" and data["start_url"] == "/"
    sizes = {icon["sizes"] for icon in data["icons"]}
    assert {"192x192", "512x512"} <= sizes
    for icon in data["icons"]:
        assert static_file(icon["src"]), icon["src"]


def test_favicon_ico_redirects_to_the_png_without_login(client):
    response = client.get("/favicon.ico")
    assert response.status_code == 301
    assert response["Location"].endswith("img/favicon-32.png")
    assert static_file(response["Location"])
