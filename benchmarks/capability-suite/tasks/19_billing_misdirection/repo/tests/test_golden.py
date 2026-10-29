"""The March 2026 invoices must match Finance's signed-off goldens byte for byte.

tests/golden/mar2026/ was produced by Finance from data/mar2026/ (sign-off FIN-2026-041).
Do not edit the goldens; a mismatch is a bug in the program.
"""

from functools import lru_cache

import pytest

from meterbill.pipeline import run_billing
from meterbill.render import render

from .helpers import DATA, GOLDEN

CYCLE = "2026-03"
CUSTOMERS = ["C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08", "C09", "C10", "C11", "C12"]


@lru_cache(maxsize=None)
def run():
    return run_billing(DATA, CYCLE)


def golden(name):
    return (GOLDEN / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("cid", CUSTOMERS)
def test_text_invoice_matches_golden(cid):
    inv = run().invoice(cid)
    assert render(inv, "text") == golden(f"KC-{CYCLE}-{cid}.txt")


@pytest.mark.parametrize("cid", ["C03", "C07", "C09"])
def test_csv_invoice_matches_golden(cid):
    assert render(run().invoice(cid), "csv") == golden(f"KC-{CYCLE}-{cid}.csv")


@pytest.mark.parametrize("cid", ["C02", "C08", "C11"])
def test_json_invoice_matches_golden(cid):
    assert render(run().invoice(cid), "json") == golden(f"KC-{CYCLE}-{cid}.json")


def test_every_invoice_adds_up():
    from meterbill.invoice import invoice_check
    for inv in run().invoices:
        assert invoice_check(inv) == [], inv.number
