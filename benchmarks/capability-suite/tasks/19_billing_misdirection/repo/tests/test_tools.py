"""explain, audit trail and budgets."""

from decimal import Decimal

import pytest

from meterbill.audit import append, compare_runs, last_for, read_trail, record_run
from meterbill.budgets import budget_status, parse_budgets
from meterbill.errors import ConfigError
from meterbill.explain import explain_invoice, explain_line
from meterbill.money import Money
from meterbill.pipeline import run_billing

from .helpers import DATA, converter
from .test_invoice import ctx
from .test_reports import _records, _starter_invoice

D = Decimal


def test_explain_usage_line():
    inv = _starter_invoice()
    ex = explain_line(ctx("T01,starter,2025-01-01\n"), inv, _records(), 1)
    labels = [lbl for lbl, _ in ex.steps]
    assert labels == ["period", "records", "aggregation", "included", "rating", "rounding"]
    assert dict(ex.steps)["aggregation"] == "sum -> 180000"
    assert ex.render().startswith("KC-2026-02-T01: API calls")


def test_explain_base_line_and_bounds():
    inv = _starter_invoice()
    c = ctx("T01,starter,2025-01-01\n")
    assert dict(explain_line(c, inv, _records(), 0).steps)["base fee"] == "49.00 USD x 1/1"
    with pytest.raises(IndexError):
        explain_line(c, inv, _records(), 9)
    assert explain_invoice(c, inv, _records()).count("KC-2026-02-T01:") == len(inv.lines)


def test_audit_trail_roundtrip(tmp_path):
    run = run_billing(DATA, "2026-03", customers=["C04", "C11"])
    entry = record_run(run)
    assert entry["invoices"] == 2 and len(entry["digest"]) == 64
    path = tmp_path / "audit.jsonl"
    append(path, entry)
    append(path, dict(entry, total_usd="0"))
    trail = read_trail(path)
    assert len(trail) == 2
    assert compare_runs(trail[0], last_for(trail, "2026-03")) == ["total_usd"]
    assert record_run(run_billing(DATA, "2026-03", customers=["C04", "C11"]))["digest"] == entry["digest"]
    with pytest.raises(ValueError):
        append(path, {"cycle": "2026-03"})


def test_budgets():
    budgets = parse_budgets("customer,currency,monthly_budget,warn_percent\nT01,USD,80.00,90\nT02,USD,10,\n")
    inv = _starter_invoice()
    st = budget_status(budgets, [inv], converter())
    assert len(st) == 1 and st[0].spent == inv.total
    assert st[0].state == ("over" if inv.total > Money("80.00", "USD") else "warning" if inv.total.amount >= 72 else "ok")
    with pytest.raises(ConfigError):
        parse_budgets("customer,currency,monthly_budget\nT01,USD,0\n")
