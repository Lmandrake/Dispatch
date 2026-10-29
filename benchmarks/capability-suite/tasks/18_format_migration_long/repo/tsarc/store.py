"""An archive store: a directory of daily archives with routed appends.

Layout::

    <root>/STORE.json             {"schema": "...", "metadata": {...}, "format_version": null}
    <root>/<YYYY>/<YYYY-MM-DD>.tsa

:meth:`Store.add` splits incoming rows by UTC day and appends each part to
that day's archive (creating it when needed); :meth:`Store.query` reads only
the days that overlap the requested range and returns one table in time order.
"""
import datetime as _dt
import json
from pathlib import Path

from .errors import QueryError, SchemaError
from .fileutil import atomic_write_bytes
from .ops.merge import merge_tables
from .schema import Schema
from .table import Table
from .timeutil import US_PER_SECOND

CONFIG = "STORE.json"
_EPOCH = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)
_DAY = 86400 * US_PER_SECOND


def _day_key(us):
    return (_EPOCH + _dt.timedelta(microseconds=us)).strftime("%Y-%m-%d")


def _day_start(key):
    d = _dt.datetime.strptime(key, "%Y-%m-%d").replace(tzinfo=_dt.timezone.utc)
    delta = d - _EPOCH
    return delta.days * _DAY


class Store:
    def __init__(self, root):
        self.root = Path(root)
        cfg = self.root / CONFIG
        if not cfg.exists():
            raise QueryError(f"not an archive store (no {CONFIG}): {self.root}")
        data = json.loads(cfg.read_text(encoding="utf-8"))
        self.schema = Schema.parse(data["schema"])
        self.metadata = dict(data.get("metadata", {}))
        self.format_version = data.get("format_version")

    @classmethod
    def create(cls, root, schema, metadata=None, format_version=None):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        if (root / CONFIG).exists():
            raise QueryError(f"a store already exists at {root}")
        if isinstance(schema, str):
            schema = Schema.parse(schema)
        cfg = {"schema": schema.to_text(), "metadata": dict(metadata or {}),
               "format_version": format_version}
        atomic_write_bytes(root / CONFIG, (json.dumps(cfg, indent=2) + "\n").encode("utf-8"))
        return cls(root)

    def path_for(self, key):
        return self.root / key[:4] / f"{key}.tsa"

    def days(self):
        out = []
        for p in sorted(self.root.glob("[0-9][0-9][0-9][0-9]/*.tsa")):
            out.append(p.stem)
        return out

    def add(self, table):
        """Append rows; returns ``{day: rows added}``."""
        from .archive import append_rows, write_archive

        if table.schema != self.schema:
            raise SchemaError(f"store schema is {self.schema.to_text()}, rows have "
                              f"{table.schema.to_text()}")
        groups = {}
        for i, t in enumerate(table.time_values()):
            groups.setdefault(_day_key(t), []).append(i)
        added = {}
        for key in sorted(groups):
            part = table.take(groups[key])
            path = self.path_for(key)
            if path.exists():
                append_rows(path, part)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                write_archive(path, part, self.metadata, self.format_version)
            added[key] = part.num_rows
        return added

    def query(self, start=None, end=None, columns=None, where=None):
        from .archive import ArchiveReader

        parts = []
        for key in self.days():
            lo = _day_start(key)
            hi = lo + _DAY
            if start is not None and hi <= start:
                continue
            if end is not None and lo >= end:
                continue
            parts.append(ArchiveReader(self.path_for(key)).query(start, end, columns, where))
        if not parts:
            sub = self.schema if columns is None else self.schema.select(columns)
            return Table(sub)
        return merge_tables(parts)

    def stats(self):
        from .archive import ArchiveReader

        out = []
        for key in self.days():
            rd = ArchiveReader(self.path_for(key))
            out.append((key, rd.num_rows, rd.size))
        return out
