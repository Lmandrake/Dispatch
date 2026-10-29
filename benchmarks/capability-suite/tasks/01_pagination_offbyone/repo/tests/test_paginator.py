from paginator import Paginator


def test_basic_pages():
    p = Paginator(list(range(20)), per_page=5)
    assert p.total_pages == 4
    assert p.page(2).items == [5, 6, 7, 8, 9]


def test_iterating_returns_every_item():
    items = list(range(21))
    p = Paginator(items, per_page=5)
    seen = [x for page in p for x in page.items]
    assert seen == items


def test_partial_last_page():
    p = Paginator(list(range(13)), per_page=5)
    last = p.page(p.total_pages)
    assert last.items == [10, 11, 12]
    assert not last.has_next
