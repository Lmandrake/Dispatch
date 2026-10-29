import pytest
from paginator import Paginator, Page


@pytest.mark.parametrize("n", range(0, 40))
@pytest.mark.parametrize("per", [1, 2, 3, 5, 7, 10])
def test_all_items_exactly_once(n, per):
    items = list(range(n))
    p = Paginator(items, per_page=per)
    expected_pages = -(-n // per)
    assert p.total_pages == expected_pages
    pages = list(p)
    assert [x for pg in pages for x in pg.items] == items
    for i, pg in enumerate(pages, 1):
        assert pg.number == i
        assert pg.has_prev == (i > 1)
        assert pg.has_next == (i < expected_pages)
        assert 1 <= len(pg.items) <= per


def test_single_trailing_item():
    p = Paginator(list(range(11)), per_page=5)
    assert p.total_pages == 3
    assert p.page(3).items == [10]
    assert p.page(2).has_next


def test_out_of_range_and_validation():
    p = Paginator(list(range(11)), per_page=5)
    for bad in (0, 4, -1):
        with pytest.raises(IndexError):
            p.page(bad)
    with pytest.raises(IndexError):
        Paginator([], per_page=3).page(1)
    with pytest.raises(ValueError):
        Paginator([1], per_page=0)
    assert isinstance(p.page(1), Page)
    assert p.count == 11
