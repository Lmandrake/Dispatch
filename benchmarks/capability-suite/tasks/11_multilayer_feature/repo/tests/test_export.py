import csv
import io
import json

import pytest

from stockroom.errors import ValidationError
from stockroom.export import (
    ITEM_CSV_COLUMNS,
    export_items,
    items_to_csv,
    items_to_json,
    items_to_table,
    orders_to_csv,
    parse_items_csv,
)
from stockroom.models import Item, Order
from stockroom.table import render_table

ITEMS = [
    Item("BOLT-001", "Hex bolt", quantity=10, price_cents=15, location="A1"),
    Item("SAW-010", "Hand saw", quantity=1, price_cents=2499),
]


def test_render_table():
    text = render_table(["SKU", "Qty"], [["BOLT-001", 5], ["A-1", 120]], "lr")
    assert text.splitlines() == ["SKU       Qty", "--------  ---", "BOLT-001    5", "A-1       120"]


def test_items_csv():
    rows = list(csv.DictReader(io.StringIO(items_to_csv(ITEMS))))
    assert tuple(rows[0]) == ITEM_CSV_COLUMNS
    assert rows[0]["price"] == "0.15" and rows[0]["value"] == "1.50"
    assert rows[1]["location"] == ""


def test_items_json():
    data = json.loads(items_to_json(ITEMS))
    assert list(data[0]) == ["sku", "name", "quantity", "price", "price_cents", "location",
                             "reorder_level", "value_cents"]
    assert data[1]["value_cents"] == 2499


def test_items_table():
    text = items_to_table(ITEMS)
    lines = text.splitlines()
    assert lines[0].split() == ["SKU", "Name", "Qty", "Price", "Location", "Value"]
    assert "-" in lines[3].split()
    assert lines[-1] == "2 items, 11 units, total value 26.49"


def test_unknown_format():
    with pytest.raises(ValidationError):
        export_items(ITEMS, "xml")


def test_orders_csv():
    text = orders_to_csv([Order(1, "A-001", 2, customer="Bob")])
    assert text.splitlines()[0] == "id,sku,quantity,customer,status,created_at,closed_at"


def test_csv_roundtrip():
    rows = parse_items_csv(items_to_csv(ITEMS))
    assert rows[0] == {"sku": "BOLT-001", "name": "Hex bolt", "quantity": 10, "price_cents": 15,
                       "location": "A1", "reorder_level": 0}
    assert "location" not in rows[1]


def test_csv_import_errors():
    with pytest.raises(ValidationError, match="missing"):
        parse_items_csv("sku,qty\nA-001,1\n")
    with pytest.raises(ValidationError, match="unknown"):
        parse_items_csv("sku,name,colour\nA-001,a,red\n")
    with pytest.raises(ValidationError, match="row 2"):
        parse_items_csv("sku,name,quantity\nA-001,a,1\nB-001,b,lots\n")
