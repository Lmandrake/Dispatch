from decimal import Decimal

import json

import pytest

from meterbill.money import Money
from meterbill.render import render
from meterbill.render.fmt import UnroundedAmount, format_amount, format_qty, format_unit_price

from .test_invoice import ctx
from .helpers import customer, rec

D = Decimal


def test_format_amount():
    assert format_amount(Money("1234.5", "USD")) == "1,234.50"
    assert format_amount(Money("-0.5", "USD")) == "-0.50"
    assert format_amount(Money("15210", "JPY")) == "15,210"
    assert format_amount(Money("1234.5", "USD"), grouping=False) == "1234.50"
    with pytest.raises(UnroundedAmount):
        format_amount(Money("1.005", "USD"), strict=True)


def test_format_qty_and_unit_price():
    assert format_qty(D("1234567")) == "1,234,567"
    assert format_qty(D("611.875"), 3) == "611.875"
    assert format_qty(D("2.5"), 3) == "2.500"
    assert format_unit_price(D("0.00025")) == "0.00025"
    assert format_unit_price(D("12")) == "12.00"
    assert format_unit_price(D("1.9")) == "1.90"


def _inv():
    c = customer(id="T01", timezone="UTC", jurisdiction="US-NY", name='Quote "Q" & Co, Ltd')
    records = [rec("T01", "api_calls", 1500000, "2026-02-10T12:00:00Z"),
               rec("T01", "seats", 4, "2026-02-10T12:00:00Z")]
    return build(c, records)


def build(c, records):
    from meterbill.invoice import build_invoice
    return build_invoice(ctx("T01,team,2025-01-01\n"), c, "2026-02", records)


def test_text_layout():
    text = render(_inv(), "text")
    lines = text.splitlines()
    assert lines[0] == "INVOICE KC-2026-02-T01"
    assert all(len(ln) <= 72 for ln in lines)
    assert "API calls: 1,500,000 calls" in text
    assert "    1,000,001-10,000,000: 500,000 @ 0.00025" in text
    assert lines[-2].endswith("775.79") or "TOTAL USD" in text


def test_csv_and_json_carry_same_figures():
    inv = _inv()
    csv_text = render(inv, "csv")
    doc = json.loads(render(inv, "json"))
    assert csv_text.splitlines()[0] == "invoice,customer,kind,description,quantity,unit,amount,currency"
    totals = {ln.split(",")[2]: ln.split(",")[-2] for ln in csv_text.splitlines()[1:] if ln.split(",")[2] in ("subtotal", "tax", "total", "due")}
    assert totals == {"subtotal": doc["subtotal"], "tax": doc["tax"]["amount"], "total": doc["total"], "due": doc["amount_due"]}
    assert doc["customer"]["name"] == 'Quote "Q" & Co, Ltd'


def test_html_escapes():
    html = render(_inv(), "html")
    assert "&quot;Q&quot; &amp; Co" in html and "<script" not in html


def test_unknown_format():
    with pytest.raises(ValueError):
        render(_inv(), "pdf")
