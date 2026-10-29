"""Item and order exports: CSV, JSON and text table, plus CSV import.

Item CSV columns, in order::

    sku,name,quantity,price,location,reorder_level,value

``price`` and ``value`` are decimal strings such as ``12.50``.

Item JSON is a list of objects with keys, in order::

    sku, name, quantity, price, price_cents, location, reorder_level, value_cents

(``price`` is the decimal string, ``price_cents`` the integer.)

The item text table has columns ``SKU  Name  Qty  Price  Location  Value``
with Qty, Price and Value right-aligned, followed by a blank line and a
``N item(s), U unit(s), total value V`` footer.

Order CSV columns: ``id,sku,quantity,customer,status,created_at,closed_at``.
"""

import csv
import io
import json

from stockroom.errors import ValidationError
from stockroom.money import format_price, parse_price
from stockroom.table import render_table

ITEM_CSV_COLUMNS = ("sku", "name", "quantity", "price", "location", "reorder_level", "value")
ORDER_CSV_COLUMNS = ("id", "sku", "quantity", "customer", "status", "created_at", "closed_at")
IMPORT_REQUIRED = ("sku", "name")
IMPORT_OPTIONAL = ("quantity", "price", "location", "reorder_level")


# ---- items ---------------------------------------------------------------

def item_row(item):
    """The CSV row for one item, as a dict keyed by ITEM_CSV_COLUMNS."""
    return {
        "sku": item.sku,
        "name": item.name,
        "quantity": item.quantity,
        "price": format_price(item.price_cents),
        "location": item.location,
        "reorder_level": item.reorder_level,
        "value": format_price(item.value_cents),
    }


def items_to_csv(items):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=ITEM_CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for item in items:
        writer.writerow(item_row(item))
    return buf.getvalue()


def item_json(item):
    return {
        "sku": item.sku,
        "name": item.name,
        "quantity": item.quantity,
        "price": format_price(item.price_cents),
        "price_cents": item.price_cents,
        "location": item.location,
        "reorder_level": item.reorder_level,
        "value_cents": item.value_cents,
    }


def items_to_json(items, indent=2):
    return json.dumps([item_json(i) for i in items], indent=indent) + "\n"


ITEM_TABLE_HEADERS = ("SKU", "Name", "Qty", "Price", "Location", "Value")
ITEM_TABLE_ALIGN = "llrrlr"


def item_table_row(item):
    return [
        item.sku,
        item.name,
        item.quantity,
        format_price(item.price_cents),
        item.location or "-",
        format_price(item.value_cents),
    ]


def items_to_table(items):
    items = list(items)
    body = render_table(ITEM_TABLE_HEADERS, [item_table_row(i) for i in items], ITEM_TABLE_ALIGN)
    units = sum(i.quantity for i in items)
    value = sum(i.value_cents for i in items)
    footer = (f"{len(items)} item{'s' if len(items) != 1 else ''}, "
              f"{units} unit{'s' if units != 1 else ''}, total value {format_price(value)}")
    return body + "\n\n" + footer + "\n"


ITEM_FORMATS = {
    "csv": items_to_csv,
    "json": items_to_json,
    "table": items_to_table,
}


def export_items(items, fmt):
    try:
        renderer = ITEM_FORMATS[fmt]
    except KeyError:
        raise ValidationError(f"unknown format {fmt!r}; choose from {', '.join(ITEM_FORMATS)}") from None
    return renderer(items)


# ---- orders --------------------------------------------------------------

def orders_to_csv(orders):
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(ORDER_CSV_COLUMNS)
    for o in orders:
        writer.writerow([o.id, o.sku, o.quantity, o.customer, o.status, o.created_at, o.closed_at])
    return buf.getvalue()


def orders_to_json(orders, indent=2):
    rows = [
        {"id": o.id, "sku": o.sku, "quantity": o.quantity, "customer": o.customer,
         "status": o.status, "created_at": o.created_at, "closed_at": o.closed_at}
        for o in orders
    ]
    return json.dumps(rows, indent=indent) + "\n"


def orders_to_table(orders):
    rows = [[o.id, o.sku, o.quantity, o.customer or "-", o.status] for o in orders]
    return render_table(("ID", "SKU", "Qty", "Customer", "Status"), rows, "rlrll") + "\n"


ORDER_FORMATS = {"csv": orders_to_csv, "json": orders_to_json, "table": orders_to_table}


def export_orders(orders, fmt):
    try:
        renderer = ORDER_FORMATS[fmt]
    except KeyError:
        raise ValidationError(f"unknown format {fmt!r}; choose from {', '.join(ORDER_FORMATS)}") from None
    return renderer(orders)


# ---- import ----------------------------------------------------------------

def parse_items_csv(text):
    """Parse item CSV text into dicts suitable for ``InventoryService.import_items``.

    The header must contain ``sku`` and ``name``; ``quantity``, ``price``,
    ``location`` and ``reorder_level`` are optional, and the ``value``
    column written by ``items_to_csv`` is accepted and ignored, so an
    export can be imported back.  Any other column is an error.  Blank
    lines are skipped.  Errors name the 1-based data row.
    """
    reader = csv.DictReader(io.StringIO(text))
    header = reader.fieldnames or []
    missing = [c for c in IMPORT_REQUIRED if c not in header]
    if missing:
        raise ValidationError(f"CSV is missing column(s): {', '.join(missing)}")
    allowed = set(IMPORT_REQUIRED) | set(IMPORT_OPTIONAL) | {"value"}
    extra = [c for c in header if c not in allowed]
    if extra:
        raise ValidationError(f"CSV has unknown column(s): {', '.join(extra)}")
    rows = []
    for n, rec in enumerate(reader, start=1):
        if not any((v or "").strip() for v in rec.values()):
            continue
        try:
            rows.append(_import_row(rec))
        except ValidationError as exc:
            raise ValidationError(f"row {n}: {exc}") from None
    return rows


def _import_row(rec):
    row = {"sku": rec["sku"], "name": rec["name"]}
    q = (rec.get("quantity") or "").strip()
    if q:
        try:
            row["quantity"] = int(q)
        except ValueError:
            raise ValidationError(f"bad quantity {q!r}") from None
    p = (rec.get("price") or "").strip()
    if p:
        row["price_cents"] = parse_price(p)
    loc = (rec.get("location") or "").strip()
    if loc:
        row["location"] = loc
    r = (rec.get("reorder_level") or "").strip()
    if r:
        try:
            row["reorder_level"] = int(r)
        except ValueError:
            raise ValidationError(f"bad reorder_level {r!r}") from None
    return row
