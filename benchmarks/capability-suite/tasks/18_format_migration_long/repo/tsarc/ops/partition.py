"""Splitting a table into one archive per time period."""
import datetime as _dt
from pathlib import Path

from ..errors import QueryError
from ..timeutil import US_PER_SECOND

_EPOCH = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)
PERIODS = ("hour", "day", "month", "year")


def period_key(us, period):
    moment = _EPOCH + _dt.timedelta(microseconds=us)
    if period == "hour":
        return moment.strftime("%Y-%m-%dT%H")
    if period == "day":
        return moment.strftime("%Y-%m-%d")
    if period == "month":
        return moment.strftime("%Y-%m")
    if period == "year":
        return moment.strftime("%Y")
    raise QueryError(f"unknown period {period!r} (expected one of {', '.join(PERIODS)})")


def split_by_period(table, period):
    """``{key: Table}`` with one table per period, keys sorted, rows in input order."""
    groups = {}
    for i, t in enumerate(table.time_values()):
        groups.setdefault(period_key(t, period), []).append(i)
    return {k: table.take(groups[k]) for k in sorted(groups)}


def write_partitions(table, directory, period, prefix="part", metadata=None, version=None):
    """Write one archive per period into ``directory`` as ``<prefix>-<key>.tsa``.

    Returns the list of ``(path, rows)`` written, in key order.
    """
    from ..archive import write_archive

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    out = []
    for key, part in split_by_period(table, period).items():
        path = directory / f"{prefix}-{key}.tsa"
        write_archive(path, part, metadata, version)
        out.append((path, part.num_rows))
    return out


def seconds(us):
    return us / US_PER_SECOND
