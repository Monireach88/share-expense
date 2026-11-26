"""One page size for every list in the app, and links that keep the page's filters.

A list shows the first 25 items, and an expense list its first 10 days. "Load more"
(templates/_pager.html) fetches the next ones with HTMX and appends them inside the page's
``.paged`` element, so the reader keeps their place.
"""

from django.core.paginator import Page, Paginator
from django.http import HttpRequest

PAGE_SIZE = 25
# Expense lists load whole days; with days collapsed, ten day lines fit on a phone screen.
DAYS_PER_PAGE = 10


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
    """A page of whole days: DAYS_PER_PAGE days at a time, so a day is never split and each
    day's total matches its rows. It offers the attributes templates/_pager.html reads.
    """

    unit = "days"

    def __init__(self, request: HttpRequest, days: list, param: str = "page"):
        pages = [days[i : i + DAYS_PER_PAGE] for i in range(0, len(days), DAYS_PER_PAGE)] or [[]]
        try:
            number = max(1, min(int(request.GET.get(param, 1)), len(pages)))
        except ValueError:
            number = 1
        self.number = number
        self.days = pages[number - 1]
        self.count = len(days)
        self.end_index = min(number * DAYS_PER_PAGE, len(days))
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
