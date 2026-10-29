"""Customer CSV export and diff."""

import pytest

from meterbill.customer_io import (COLUMNS, customers_to_csv, diff_customer_files, diff_customers, render_diff)
from meterbill.customers import parse_customers
from meterbill.errors import ConfigError

from .helpers import DATA

HEAD = "id,name,timezone,anchor_day,currency,jurisdiction,tax_id,email,terms_days,status\n"
OLD = HEAD + ("C01,Acme,America/New_York,1,USD,US-NY,,ap@acme.example,30,active\n"
              "C02,Brightline,Europe/Berlin,1,EUR,DE,DE 811 907 980,r@b.example,14,active\n"
              "C03,Cobalt,America/Los_Angeles,15,USD,US-CA,,,30,active\n")
NEW = HEAD + ("C01,Acme Inc,America/New_York,1,USD,US-NY,,ap@acme.example,45,active\n"
              "C02,Brightline,Europe/Berlin,1,EUR,de,DE811907980,r@b.example,14,suspended\n"
              "C04,Dunmore,Europe/London,1,GBP,GB,,,30,active\n")


def test_columns_fixed_and_sorted_rows():
    text = customers_to_csv(parse_customers(NEW))
    lines = text.splitlines()
    assert lines[0] == ",".join(COLUMNS)
    assert [ln.split(",")[0] for ln in lines[1:]] == ["C01", "C02", "C04"]


def test_round_trip_sample_data():
    book = parse_customers((DATA / "customers.csv").read_text())
    text = customers_to_csv(book)
    assert parse_customers(text) == book
    assert customers_to_csv(parse_customers(text)) == text


def test_export_from_iterable_and_quoting():
    book = parse_customers(HEAD + 'C09,"Harbour, Co",UTC,1,USD,US-NY,,,30,active\n')
    text = customers_to_csv(list(book.values()))
    assert '"Harbour, Co"' in text
    assert parse_customers(text)["C09"].name == "Harbour, Co"


def test_diff_added_removed_changed():
    d = diff_customer_files(OLD, NEW)
    assert [c.id for c in d.added] == ["C04"] and [c.id for c in d.removed] == ["C03"]
    assert {ch.name: (ch.old, ch.new) for ch in d.changed["C01"]} == {
        "name": ("Acme", "Acme Inc"), "terms_days": ("30", "45")}
    assert [ch.name for ch in d.changed["C02"]] == ["status"]
    assert d.changes_to("status") == [("C02", d.changed["C02"][0])]


def test_normalisation_hides_cosmetic_changes():
    d = diff_customer_files(OLD, NEW)
    assert "jurisdiction" not in [c.name for c in d.changed["C02"]]
    assert "tax_id" not in [c.name for c in d.changed["C02"]]


def test_identical_files():
    d = diff_customer_files(OLD, OLD)
    assert d.empty and render_diff(d) == "No differences.\n"


def test_render_diff():
    text = render_diff(diff_customer_files(OLD, NEW))
    assert text.splitlines()[0] == "Customers added: 1, removed: 1, changed: 2"
    assert "+ C04  Dunmore (GBP, GB, active)" in text
    assert "- C03  Cobalt" in text
    assert "    terms_days: 30 -> 45" in text
    assert "(empty)" not in text
    cleared = diff_customers(parse_customers(OLD), parse_customers(OLD.replace("ap@acme.example", "")))
    assert "email: ap@acme.example -> (empty)" in render_diff(cleared)


def test_bad_file_raises_config_error_with_source():
    with pytest.raises(ConfigError, match="new/customers.csv"):
        diff_customer_files(OLD, HEAD + "c1,X,UTC,1,USD,US-NY,,,30,bogus\n")
