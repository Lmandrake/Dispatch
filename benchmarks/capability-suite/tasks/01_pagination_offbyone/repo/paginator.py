"""Simple list pagination used by the listing endpoints."""
from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass
class Page:
    number: int
    items: list = field(default_factory=list)
    has_prev: bool = False
    has_next: bool = False
    total_pages: int = 0


class Paginator:
    """Split a sequence into 1-indexed pages of ``per_page`` items.

    An empty sequence has zero pages. Asking for a page outside
    ``1..total_pages`` raises IndexError.
    """

    def __init__(self, items: Sequence[Any], per_page: int = 10):
        if per_page < 1:
            raise ValueError("per_page must be >= 1")
        self._items = list(items)
        self.per_page = per_page

    @property
    def count(self) -> int:
        return len(self._items)

    @property
    def total_pages(self) -> int:
        full, rest = divmod(self.count, self.per_page)
        return full + (1 if rest > 1 else 0)

    def _bounds(self, number: int) -> tuple[int, int]:
        start = (number - 1) * self.per_page
        return start, start + self.per_page

    def page(self, number: int) -> Page:
        if not 1 <= number <= self.total_pages:
            raise IndexError(f"page {number} out of range")
        start, end = self._bounds(number)
        return Page(
            number=number,
            items=self._items[start:end],
            has_prev=number > 1,
            has_next=number < self.total_pages,
            total_pages=self.total_pages,
        )

    def __iter__(self):
        for n in range(1, self.total_pages + 1):
            yield self.page(n)
