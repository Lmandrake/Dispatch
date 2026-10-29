import pytest

from stockroom.errors import QueryError
from stockroom.models import Item
from stockroom.query import compile_query, filter_items, parse, tokenize
from stockroom.query.ast import describe

ITEMS = [
    Item("BOLT-001", "Hex bolt M6", quantity=120, price_cents=15, location="A1", reorder_level=50),
    Item("NUT-001", "Hex nut M6", quantity=40, price_cents=5, location="A2", reorder_level=50),
    Item("SAW-010", "Hand saw", quantity=3, price_cents=2499, location="Tools", reorder_level=1),
    Item("TAPE-100", "Duct tape", quantity=0, price_cents=650, location=""),
]


def skus(q):
    return [i.sku for i in filter_items(ITEMS, q)]


def test_tokenize_kinds():
    kinds = [t.kind for t in tokenize("qty >= 5 and name ~ 'hex nut' (")]
    assert kinds == ["WORD", "OP", "WORD", "WORD", "WORD", "OP", "STRING", "LPAREN", "EOF"]


def test_empty_matches_all():
    assert skus("") == ["BOLT-001", "NUT-001", "SAW-010", "TAPE-100"]
    assert parse("   ") is None


@pytest.mark.parametrize("q,expected", [
    ("qty < 5", ["SAW-010", "TAPE-100"]),
    ("quantity >= 40", ["BOLT-001", "NUT-001"]),
    ("name ~ HEX", ["BOLT-001", "NUT-001"]),
    ("loc = A1 or loc = Tools", ["BOLT-001", "SAW-010"]),
    ("price > 1", ["SAW-010", "TAPE-100"]),
    ("price = 0.05", ["NUT-001"]),
    ("value >= 18", ["BOLT-001", "SAW-010"]),
    ("low", ["NUT-001"]),
    ("not low and qty > 0", ["BOLT-001", "SAW-010"]),
    ("sku in (NUT-001, TAPE-100)", ["NUT-001", "TAPE-100"]),
    ("location = ''", ["TAPE-100"]),
    ("name ~ hex qty < 100", ["NUT-001"]),
    ("(loc ~ a or qty = 0) and not sku = NUT-001", ["BOLT-001", "TAPE-100"]),
])
def test_queries(q, expected):
    assert skus(q) == expected


def test_precedence():
    assert describe(parse("low or qty < 1 and price > 2")) == "(low or (quantity < 1 and price > 2))"


@pytest.mark.parametrize("bad", [
    "colour = red", "qty ~ 3", "qty < many", "price > cheap", "name <", "(low", "low)",
    "and low", "name = 'open", "qty # 3", "low = maybe",
])
def test_errors(bad):
    with pytest.raises(QueryError):
        compile_query(bad)


def test_error_position():
    with pytest.raises(QueryError) as exc:
        compile_query("qty < 5 and colour = red")
    assert exc.value.position == 12
