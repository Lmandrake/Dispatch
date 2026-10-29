"""Seat-service key=value audit log reader.

Each line is a timestamp followed by ``key=value`` pairs:

    2026-03-02T09:00:00+01:00 event=se-0001 cust=C02 metric=seats qty=12 by="ops bot"

* Values containing spaces are double-quoted; ``\\"`` inside quotes is a
  literal quote.
* Required keys: event, cust, metric, qty.  Unknown keys are ignored.
* Lines starting with ``#`` and blank lines are ignored.
"""

from ..timeutil import parse_instant
from .records import FeedResult, UsageRecord, check_quantity

REQUIRED = ("event", "cust", "metric", "qty")


def tokenize(line):
    """Split a log line into tokens, honouring double quotes."""
    tokens = []
    buf = []
    in_quotes = False
    i = 0
    while i < len(line):
        ch = line[i]
        if in_quotes:
            if ch == "\\" and i + 1 < len(line) and line[i + 1] == '"':
                buf.append('"')
                i += 2
                continue
            if ch == '"':
                in_quotes = False
            else:
                buf.append(ch)
        elif ch == '"':
            in_quotes = True
        elif ch.isspace():
            if buf:
                tokens.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
        i += 1
    if in_quotes:
        raise ValueError("unterminated quote")
    if buf:
        tokens.append("".join(buf))
    return tokens


def parse_line(line):
    """Return (timestamp_text, {key: value}) for one log line."""
    tokens = tokenize(line)
    if not tokens:
        raise ValueError("empty line")
    stamp, pairs = tokens[0], {}
    for tok in tokens[1:]:
        key, sep, value = tok.partition("=")
        if not sep or not key:
            raise ValueError(f"not a key=value pair: {tok!r}")
        if key in pairs:
            raise ValueError(f"duplicate key {key!r}")
        pairs[key] = value
    return stamp, pairs


def read_kv_feed(text, source="feed.log"):
    result = FeedResult(source)
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            stamp, pairs = parse_line(line)
            for key in REQUIRED:
                if not pairs.get(key):
                    raise ValueError(f"missing {key}")
            rec = UsageRecord(
                event_id=pairs["event"],
                customer=pairs["cust"].upper(),
                metric=pairs["metric"],
                quantity=check_quantity(pairs["qty"]),
                at=parse_instant(stamp),
                source=source,
                line=lineno,
                note=pairs.get("by", ""),
            )
        except ValueError as e:
            result.reject(lineno, str(e), line)
            continue
        result.add(rec)
    return result
