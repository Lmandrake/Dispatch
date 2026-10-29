import pytest

from ledgerkit.accounts import Chart, ancestors, is_valid_name, truncate
from ledgerkit.errors import AccountError


def make():
    c = Chart()
    for a in ["Expenses:Travel:Air", "Expenses:Travel:Hotel", "Expenses:Office:Supplies",
              "Expenses:Office:Software", "Income:Consulting"]:
        c.declare(a)
    return c


def test_names():
    assert is_valid_name("Expenses:Travel:Air")
    assert not is_valid_name("Stuff:Things")
    assert not is_valid_name("Expenses:travel")
    assert ancestors("Expenses:Travel:Air") == ["Expenses:Travel", "Expenses"]
    assert truncate("Expenses:Travel:Air", 2) == "Expenses:Travel"
    assert truncate("Expenses:Travel:Air", None) == "Expenses:Travel:Air"


def test_resolve_order():
    c = make()
    c.add_alias("air", "Expenses:Travel:Air")
    assert c.resolve("Expenses:Travel:Air") == "Expenses:Travel:Air"
    assert c.resolve("AIR") == "Expenses:Travel:Air"
    assert c.resolve("expenses:travel:hotel") == "Expenses:Travel:Hotel"
    assert c.resolve("exp:trav:h") == "Expenses:Travel:Hotel"
    assert c.resolve("exp:off:sup") == "Expenses:Office:Supplies"


def test_ambiguous_abbreviation():
    c = make()
    with pytest.raises(AccountError, match="ambiguous"):
        c.resolve("exp:off:s")


def test_non_strict_declares_and_strict_refuses():
    c = make()
    assert c.resolve("Expenses:Travel:Taxi") == "Expenses:Travel:Taxi"
    assert "Expenses:Travel:Taxi" in c
    c.strict = True
    with pytest.raises(AccountError, match="unknown"):
        c.resolve("Expenses:Travel:Train")


def test_alias_conflict():
    c = make()
    c.add_alias("x", "Expenses:Travel:Air")
    c.add_alias("X", "Expenses:Travel:Air")
    with pytest.raises(AccountError):
        c.add_alias("x", "Income:Consulting")


def test_children_and_ancestors():
    c = make()
    assert c.children("Expenses:Travel") == ["Expenses:Travel:Air", "Expenses:Travel:Hotel"]
    assert "Expenses" in c.with_ancestors()
