"""Shared fixtures-by-function for the test suite."""

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from meterbill.catalog import parse_catalog
from meterbill.customers import Customer
from meterbill.fx import Converter, parse_rates
from meterbill.meters.records import UsageRecord

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "mar2026"
GOLDEN = ROOT / "tests" / "golden" / "mar2026"
D = Decimal
UTC = timezone.utc


def catalog():
    return parse_catalog((DATA / "catalog.toml").read_text())


def converter():
    return Converter(parse_rates((DATA / "fx_rates.csv").read_text()))


def customer(**kw):
    base = dict(id="T01", name="Test Co", timezone="UTC", anchor_day=1, currency="USD",
                jurisdiction="US-NY", tax_id="", email="", terms_days=30, status="active")
    base.update(kw)
    return Customer(**base)


def rec(cust, metric, qty, at, eid=None, note=""):
    if isinstance(at, str):
        from meterbill.timeutil import parse_instant
        at = parse_instant(at)
    rec.n = getattr(rec, "n", 0) + 1
    return UsageRecord(eid or f"t-{rec.n}", cust, metric, D(str(qty)), at, "test", rec.n, note)


def utc(*a):
    return datetime(*a, tzinfo=UTC)


__all__ = ["ROOT", "DATA", "GOLDEN", "D", "catalog", "converter", "customer", "rec", "utc", "date"]
