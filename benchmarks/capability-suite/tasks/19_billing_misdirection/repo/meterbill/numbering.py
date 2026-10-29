"""Invoice numbers and dates.

Invoice number: ``KC-<cycle>-<customer id>``, e.g. ``KC-2026-03-C07``.
A re-issued (corrected) invoice gets ``-R1``, ``-R2``, ... appended.

Issue date: the first local day after the period (the period's ``end``).
Due date: issue date + the customer's payment terms.  When the due date
falls on a Saturday or Sunday it moves to the following Monday.
"""

from datetime import timedelta

PREFIX = "KC"


def invoice_number(cycle, customer_id, revision=0):
    base = f"{PREFIX}-{cycle}-{customer_id}"
    return f"{base}-R{revision}" if revision else base


def parse_invoice_number(text):
    """Inverse of invoice_number: returns (cycle, customer_id, revision)."""
    parts = text.split("-")
    if len(parts) < 4 or parts[0] != PREFIX:
        raise ValueError(f"not an invoice number: {text!r}")
    cycle = f"{parts[1]}-{parts[2]}"
    cid = parts[3]
    rev = 0
    if len(parts) == 5:
        if not parts[4].startswith("R") or not parts[4][1:].isdigit():
            raise ValueError(f"bad revision in {text!r}")
        rev = int(parts[4][1:])
    elif len(parts) > 5:
        raise ValueError(f"not an invoice number: {text!r}")
    return cycle, cid, rev


def issue_date(period):
    return period.end


def roll_weekend(day):
    if day.weekday() == 5:
        return day + timedelta(days=2)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def due_date(period, terms_days):
    return roll_weekend(issue_date(period) + timedelta(days=terms_days))
