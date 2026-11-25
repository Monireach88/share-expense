"""Fast repeat visits: the service worker (templates/sw.js) shows the last copy of a page at
once, then fetches the fresh copy and swaps it in if anything changed.

The server decides what the service worker may keep:
- ``cacheable_page`` marks the read-only pages (trip list and the four trip tabs).
- ``PageCacheMiddleware`` un-marks a page that shows a one-time message ("Added: ..."), tells
  browsers and Cloudflare to always check HTML with the server, and adds ``X-Page-Hash`` so the
  service worker can tell whether the fresh copy differs from the stored one.
"""

import hashlib
import re
from functools import wraps

from django.contrib.auth.decorators import login_not_required
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.templatetags.static import static

CACHE_HEADER = "X-SW-Cache"
# Django gives every response a fresh masked CSRF token, so it is left out of the hash.
CSRF_TOKEN = re.compile(rb'(csrfmiddlewaretoken" value="|"X-CSRFToken": ")[^"]+')


def cacheable_page(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        response = view(request, *args, **kwargs)
        if request.method == "GET" and response.status_code == 200:
            response[CACHE_HEADER] = "page"
        return response

    return wrapper


class PageCacheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if not response.get("Content-Type", "").startswith("text/html") or response.streaming:
            return response
        response.setdefault("Cache-Control", "private, no-cache")
        storage = getattr(request, "_messages", None)
        if storage is not None and storage.used:
            # A one-time message must not come back from the stored copy.
            response.headers.pop(CACHE_HEADER, None)
            response["Cache-Control"] = "private, no-store"
        if CACHE_HEADER in response:
            response["X-Page-Hash"] = hashlib.sha1(
                CSRF_TOKEN.sub(rb"\1", response.content), usedforsecurity=False
            ).hexdigest()
        return response


@login_not_required
def service_worker(request: HttpRequest) -> HttpResponse:
    # The version changes with every change to the static files, so a deploy installs a new
    # worker, which deletes the pages stored by the old one.
    files = [static(name) for name in ("css/app.css", "js/app.js", "img/icons.svg")]
    version = hashlib.sha1("|".join(files).encode(), usedforsecurity=False).hexdigest()[:12]
    body = render_to_string("sw.js", {"version": version, "static_files": files})
    response = HttpResponse(body, content_type="text/javascript; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    response["Service-Worker-Allowed"] = "/"
    return response
