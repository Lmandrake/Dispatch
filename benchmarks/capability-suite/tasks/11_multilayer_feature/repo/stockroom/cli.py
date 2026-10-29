"""Command line interface: ``python3 -m stockroom [--db PATH] COMMAND ...``.

The database path comes from ``--db``, else the STOCKROOM_DB environment
variable, else ``stockroom.json`` in the current directory.  ``--db :memory:``
uses a throwaway in-memory store (handy for trying commands out).

Exit status: 0 on success, 1 for a StockroomError (printed to stderr as
``error: <message>``), 2 for a usage error (argparse's own behaviour).

Commands
--------
add SKU NAME [--qty N] [--price P] [--location L] [--reorder N]
update SKU [--name N] [--price P] [--location L] [--reorder N]
remove SKU
receive SKU QTY [--note TEXT]
adjust SKU DELTA --reason TEXT
show SKU
list [--where QUERY] [--low] [--location L] [--format table|csv|json]
order place SKU QTY [--customer NAME]
order fulfil ID
order cancel ID [--reason TEXT]
order list [--status S] [--sku SKU] [--format table|csv|json]
history [--sku SKU] [--action A] [--since SEQ] [--json]
report [summary|locations|orders]
export items|orders [--format csv|json|table] [--where QUERY] [--output FILE]
import FILE.csv
"""

import argparse
import json
import os
import sys

from stockroom.audit import format_event
from stockroom.errors import StockroomError, ValidationError
from stockroom.export import export_items, export_orders, parse_items_csv
from stockroom.money import format_price, parse_price
from stockroom.report import REPORTS
from stockroom.services import InventoryService
from stockroom.storage import open_repository
from stockroom.storage.jsonfile import event_to_dict

DEFAULT_DB = "stockroom.json"


# ---- argument types ----------------------------------------------------------

def _int_arg(text):
    try:
        return int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from None


def _price_arg(text):
    try:
        return parse_price(text)
    except ValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


# ---- parser -------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(prog="stockroom", description="Small inventory and order tracker.")
    p.add_argument("--db", help="database file (default: $STOCKROOM_DB or ./stockroom.json)")
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    a = sub.add_parser("add", help="add a new item")
    a.add_argument("sku")
    a.add_argument("name")
    a.add_argument("--qty", type=_int_arg, default=0)
    a.add_argument("--price", type=_price_arg, default=0)
    a.add_argument("--location", default="")
    a.add_argument("--reorder", type=_int_arg, default=0)

    u = sub.add_parser("update", help="change an item's details")
    u.add_argument("sku")
    u.add_argument("--name")
    u.add_argument("--price", type=_price_arg)
    u.add_argument("--location")
    u.add_argument("--reorder", type=_int_arg)

    r = sub.add_parser("remove", help="remove an item")
    r.add_argument("sku")

    rc = sub.add_parser("receive", help="book incoming stock")
    rc.add_argument("sku")
    rc.add_argument("qty", type=_int_arg)
    rc.add_argument("--note", default="")

    adj = sub.add_parser("adjust", help="correct stock by a signed delta")
    adj.add_argument("sku")
    adj.add_argument("delta", type=_int_arg)
    adj.add_argument("--reason", required=True)

    s = sub.add_parser("show", help="show one item")
    s.add_argument("sku")

    ls = sub.add_parser("list", help="list items")
    ls.add_argument("--where", default="", help="filter query, e.g. 'qty < 5 and loc ~ A'")
    ls.add_argument("--low", action="store_true", help="only items at or below reorder level")
    ls.add_argument("--location", help="only items at exactly this location")
    ls.add_argument("--format", choices=("table", "csv", "json"), default="table")

    o = sub.add_parser("order", help="place, fulfil, cancel or list orders")
    osub = o.add_subparsers(dest="order_command", required=True, metavar="ACTION")
    op = osub.add_parser("place")
    op.add_argument("sku")
    op.add_argument("qty", type=_int_arg)
    op.add_argument("--customer", default="")
    of = osub.add_parser("fulfil", aliases=["fulfill"])
    of.add_argument("id", type=_int_arg)
    oc = osub.add_parser("cancel")
    oc.add_argument("id", type=_int_arg)
    oc.add_argument("--reason", default="")
    ol = osub.add_parser("list")
    ol.add_argument("--status", choices=("open", "fulfilled", "cancelled"))
    ol.add_argument("--sku")
    ol.add_argument("--format", choices=("table", "csv", "json"), default="table")

    h = sub.add_parser("history", help="show the audit trail")
    h.add_argument("--sku", help="only events for this SKU")
    h.add_argument("--action", help="exact action, or a prefix ending in '.' such as 'order.'")
    h.add_argument("--since", type=_int_arg, default=0, help="only events with seq > SINCE")
    h.add_argument("--json", action="store_true", help="one JSON object per line")

    rep = sub.add_parser("report", help="print a summary report")
    rep.add_argument("name", nargs="?", default="summary", choices=sorted(REPORTS))

    ex = sub.add_parser("export", help="export items or orders")
    ex.add_argument("what", choices=("items", "orders"))
    ex.add_argument("--format", choices=("csv", "json", "table"), default="csv")
    ex.add_argument("--where", default="", help="filter query (items only)")
    ex.add_argument("--output", "-o", help="write to this file instead of stdout")

    im = sub.add_parser("import", help="add items from a CSV file (all or nothing)")
    im.add_argument("file")

    return p


# ---- command handlers ------------------------------------------------------------

def cmd_add(svc, args, out):
    item = svc.add_item(args.sku, args.name, quantity=args.qty, price_cents=args.price,
                        location=args.location, reorder_level=args.reorder)
    print(f"added {item.sku}", file=out)


def cmd_update(svc, args, out):
    before = svc.get(args.sku)
    item = svc.update_item(args.sku, name=args.name, price_cents=args.price,
                           location=args.location, reorder_level=args.reorder)
    if item == before:
        print(f"{item.sku} unchanged", file=out)
    else:
        print(f"updated {item.sku}", file=out)


def cmd_remove(svc, args, out):
    item = svc.remove_item(args.sku)
    print(f"removed {item.sku}", file=out)


def cmd_receive(svc, args, out):
    item = svc.receive(args.sku, args.qty, note=args.note)
    print(f"{item.sku}: {item.quantity} on hand", file=out)


def cmd_adjust(svc, args, out):
    item = svc.adjust(args.sku, args.delta, args.reason)
    print(f"{item.sku}: {item.quantity} on hand", file=out)


def show_lines(svc, item):
    """The ``key: value`` lines printed by ``stockroom show``."""
    reserved = svc.reserved(item.sku)
    return [
        f"SKU:        {item.sku}",
        f"Name:       {item.name}",
        f"On hand:    {item.quantity}",
        f"Reserved:   {reserved}",
        f"Available:  {item.quantity - reserved}",
        f"Price:      {format_price(item.price_cents)}",
        f"Value:      {format_price(item.value_cents)}",
        f"Location:   {item.location or '-'}",
        f"Reorder at: {item.reorder_level}",
        f"Created:    {item.created_at}",
        f"Updated:    {item.updated_at}",
    ]


def cmd_show(svc, args, out):
    item = svc.get(args.sku)
    print("\n".join(show_lines(svc, item)), file=out)


def _selected_items(svc, args):
    items = svc.items(args.where)
    if getattr(args, "low", False):
        items = [i for i in items if i.is_low]
    location = getattr(args, "location", None)
    if location is not None:
        items = [i for i in items if i.location == location]
    return items


def cmd_list(svc, args, out):
    out.write(export_items(_selected_items(svc, args), args.format))


def cmd_order(svc, args, out):
    c = args.order_command
    if c == "place":
        order = svc.place_order(args.sku, args.qty, customer=args.customer)
        print(f"order {order.id} placed: {order.quantity} x {order.sku}", file=out)
    elif c in ("fulfil", "fulfill"):
        order = svc.fulfil_order(args.id)
        print(f"order {order.id} fulfilled", file=out)
    elif c == "cancel":
        order = svc.cancel_order(args.id, reason=args.reason)
        print(f"order {order.id} cancelled", file=out)
    elif c == "list":
        out.write(export_orders(svc.orders(status=args.status, sku=args.sku), args.format))
    else:  # pragma: no cover - argparse prevents this
        raise AssertionError(c)


def cmd_history(svc, args, out):
    subject = None
    if args.sku:
        from stockroom.validation import normalize_sku
        subject = normalize_sku(args.sku)
    events = svc.audit.events(subject=subject, action=args.action, since_seq=args.since)
    for ev in events:
        if args.json:
            print(json.dumps(event_to_dict(ev), sort_keys=True), file=out)
        else:
            print(format_event(ev), file=out)


def cmd_report(svc, args, out):
    out.write(REPORTS[args.name](svc))


def cmd_export(svc, args, out):
    if args.what == "items":
        text = export_items(svc.items(args.where), args.format)
    else:
        if args.where:
            raise ValidationError("--where only applies to items")
        text = export_orders(svc.orders(), args.format)
    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        print(f"wrote {args.output}", file=out)
    else:
        out.write(text)


def cmd_import(svc, args, out):
    try:
        with open(args.file, encoding="utf-8", newline="") as fh:
            text = fh.read()
    except OSError as exc:
        raise ValidationError(f"cannot read {args.file}: {exc.strerror}") from None
    added = svc.import_items(parse_items_csv(text))
    print(f"imported {len(added)} item{'s' if len(added) != 1 else ''}", file=out)


HANDLERS = {
    "add": cmd_add,
    "update": cmd_update,
    "remove": cmd_remove,
    "receive": cmd_receive,
    "adjust": cmd_adjust,
    "show": cmd_show,
    "list": cmd_list,
    "order": cmd_order,
    "history": cmd_history,
    "report": cmd_report,
    "export": cmd_export,
    "import": cmd_import,
}


def main(argv=None, out=None, err=None):
    out = out or sys.stdout
    err = err or sys.stderr
    args = build_parser().parse_args(argv)
    db = args.db or os.environ.get("STOCKROOM_DB") or DEFAULT_DB
    try:
        svc = InventoryService(open_repository(db))
        HANDLERS[args.command](svc, args, out)
    except StockroomError as exc:
        print(f"error: {exc}", file=err)
        return 1
    return 0
