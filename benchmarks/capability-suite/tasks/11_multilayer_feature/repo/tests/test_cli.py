import json

import pytest

from tests.helpers import run_cli


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKROOM_NOW", "2026-03-01T12:00:00Z")
    path = tmp_path / "stock.json"
    assert run_cli("add", "BOLT-0042", "Hex bolt M6", "--qty", "120", "--price", "0.15",
                   "--location", "A1", "--reorder", "50", db=path)[0] == 0
    assert run_cli("add", "SAW-010", "Hand saw", "--qty", "3", "--price", "24.99", db=path)[0] == 0
    return path


def test_add_and_show(db):
    rc, out, _ = run_cli("show", "bolt-0042", db=db)
    assert rc == 0
    assert "SKU:        BOLT-0042" in out
    assert "Location:   A1" in out
    assert "Created:    2026-03-01T12:00:00Z" in out


def test_errors_exit_1(db):
    rc, out, err = run_cli("add", "BOLT-0042", "dup", db=db)
    assert rc == 1 and err.startswith("error: ")
    rc, _, err = run_cli("list", "--where", "qty <", db=db)
    assert rc == 1 and "expected a value" in err


def test_list_formats(db):
    rc, out, _ = run_cli("list", "--format", "csv", "--where", "price > 1", db=db)
    assert out.splitlines() == ["sku,name,quantity,price,location,reorder_level,value",
                                "SAW-010,Hand saw,3,24.99,,0,74.97"]
    rc, out, _ = run_cli("list", "--format", "json", db=db)
    assert [d["sku"] for d in json.loads(out)] == ["BOLT-0042", "SAW-010"]
    rc, out, _ = run_cli("list", db=db)
    assert out.splitlines()[-1] == "2 items, 123 units, total value 92.97"


def test_order_flow_and_history(db):
    assert run_cli("order", "place", "BOLT-0042", "30", "--customer", "Line 3", db=db)[1] == \
        "order 1 placed: 30 x BOLT-0042\n"
    rc, out, _ = run_cli("show", "BOLT-0042", db=db)
    assert "Available:  90" in out
    assert run_cli("order", "fulfill", "1", db=db)[0] == 0
    rc, out, _ = run_cli("order", "list", "--format", "csv", db=db)
    assert out.splitlines()[1].startswith("1,BOLT-0042,30,Line 3,fulfilled,")
    rc, out, _ = run_cli("history", "--action", "order.", "--json", db=db)
    actions = [json.loads(l)["action"] for l in out.splitlines()]
    assert actions == ["order.placed", "order.fulfilled"]
    rc, out, _ = run_cli("history", "--sku", "saw-010", db=db)
    assert out.splitlines() == [
        "#2 2026-03-01T12:00:00Z item.added SAW-010 location='' name='Hand saw' price_cents=2499 quantity=3"
    ]


def test_report(db):
    rc, out, _ = run_cli("report", db=db)
    assert "Items:        2" in out
    rc, out, _ = run_cli("report", "locations", db=db)
    assert out.splitlines()[-1].split() == ["-", "1", "3", "74.97"]


def test_export_and_import(db, tmp_path):
    out_file = tmp_path / "items.csv"
    rc, out, _ = run_cli("export", "items", "-o", str(out_file), db=db)
    assert rc == 0 and out == f"wrote {out_file}\n"
    other = tmp_path / "other.json"
    rc, out, _ = run_cli("import", str(out_file), db=other)
    assert (rc, out) == (0, "imported 2 items\n")
    rc, out, _ = run_cli("import", str(out_file), db=other)
    assert rc == 1


def test_update_unchanged(db):
    assert run_cli("update", "SAW-010", "--price", "24.99", db=db)[1] == "SAW-010 unchanged\n"
    assert run_cli("update", "SAW-010", "--location", "T2", db=db)[1] == "updated SAW-010\n"
