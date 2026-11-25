"""One page size for every list in the app, and links that keep the page's filters.

The page shows the first 25 items; "Load more" (templates/_pager.html) fetches the next 25 with
HTMX and appends the items inside the page's ``.paged`` element, so the reader keeps their place.
"""

from django.core.paginator import Page, Paginator
from django.http import HttpRequest

PAGE_SIZE = 25


def paginate(request: HttpRequest, items, param: str = "page") -> Page:
    """The requested page of ``items``; a missing or wrong page number gives the nearest page."""
    page = Paginator(items, PAGE_SIZE).get_page(request.GET.get(param))
    query = request.GET.copy()
    query.pop(param, None)
    # The pager template appends "page=N" to this, so links keep the other filters.
    page.base_query = f"{query.urlencode()}&" if query else ""
    page.param = param
    return page


class DayPage:
    """A page of day groups that never splits a day, so each day total matches its rows.

    A page holds whole days until it has at least PAGE_SIZE rows; a single long day stays whole.
    It offers the attributes templates/_pager.html reads from a Django Page.
    """

    def __init__(self, request: HttpRequest, days: list, param: str = "page"):
        pages: list[list] = [[]]
        for day in days:
            if sum(len(d[1]) for d in pages[-1]) >= PAGE_SIZE:
                pages.append([])
            pages[-1].append(day)
        try:
            number = max(1, min(int(request.GET.get(param, 1)), len(pages)))
        except ValueError:
            number = 1
        self.number = number
        self.days = pages[number - 1]
        self.count = sum(len(d[1]) for d in days)
        self.end_index = sum(len(d[1]) for page in pages[:number] for d in page)
        self.num_pages = len(pages)
        query = request.GET.copy()
        query.pop(param, None)
        self.base_query = f"{query.urlencode()}&" if query else ""
        self.param = param

    @property
    def paginator(self):
        return self  # The pager template reads page.paginator.count.

    def has_next(self) -> bool:
        return self.number < self.num_pages

    def next_page_number(self) -> int:
        return self.number + 1
