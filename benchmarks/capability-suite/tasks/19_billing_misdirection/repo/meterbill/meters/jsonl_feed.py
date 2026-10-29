"""Storage-service JSON-lines reader.

One JSON object per line:

    {"id": "st-0001", "customer": "C02", "metric": "storage_gb",
     "value": "512.5", "unit": "GB", "ts": 1772323200}

* ``value`` is a decimal string or an integer (floats are rejected: storage
  sizes must not pick up binary rounding error).
* ``unit`` is one of B, KB, MB, GB, TB (decimal multiples: 1 GB = 1000 MB)
  and is converted to the metric's unit, GB.  Missing unit means GB.
* ``ts``: epoch seconds or milliseconds, or an ISO string.
* Blank lines are ignored; a line that is not a JSON object is rejected.
"""

import json
from decimal import Decimal

from datetime import datetime, timezone

from ..timeutil import parse_instant

UTC = timezone.utc
from .records import FeedResult, UsageRecord, check_quantity

UNIT_FACTORS = {
    "B": Decimal("0.000000001"),
    "KB": Decimal("0.000001"),
    "MB": Decimal("0.001"),
    "GB": Decimal(1),
    "TB": Decimal(1000),
}


def to_gb(value, unit):
    unit = (unit or "GB").strip().upper()
    try:
        factor = UNIT_FACTORS[unit]
    except KeyError:
        raise ValueError(f"unknown storage unit {unit!r}") from None
    return value * factor


def read_jsonl_feed(text, source="feed.jsonl"):
    result = FeedResult(source)
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line, parse_float=_no_float)
        except (json.JSONDecodeError, ValueError) as e:
            result.reject(lineno, f"bad JSON: {e}", line)
            continue
        if not isinstance(obj, dict):
            result.reject(lineno, "not a JSON object", line)
            continue
        try:
            for key in ("id", "customer", "metric", "value", "ts"):
                if obj.get(key) in (None, ""):
                    raise ValueError(f"missing {key}")
            qty = check_quantity(obj["value"])
            metric = str(obj["metric"])
            if metric == "storage_gb":
                qty = to_gb(qty, obj.get("unit"))
            elif obj.get("unit") not in (None, ""):
                raise ValueError(f"unit given for non-storage metric {metric}")
            rec = UsageRecord(
                event_id=str(obj["id"]),
                customer=str(obj["customer"]).upper(),
                metric=metric,
                quantity=qty,
                at=snapshot_time(obj["ts"]),
                source=source,
                line=lineno,
                note=str(obj.get("note", "")),
            )
        except ValueError as e:
            result.reject(lineno, str(e), line)
            continue
        result.add(rec)
    return result


def snapshot_time(ts):
    """The UTC instant of a snapshot's ``ts`` field."""
    if isinstance(ts, int) and not isinstance(ts, bool):
        return parse_instant(str(ts))
    if not isinstance(ts, str):
        raise ValueError(f"bad ts {ts!r}")
    text = ts.strip()
    if text.isdigit():
        return parse_instant(text)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        raise ValueError(f"bad ts {ts!r}") from None
    return dt.replace(tzinfo=UTC)


def _no_float(text):
    raise ValueError(f"float literal {text} not allowed")
