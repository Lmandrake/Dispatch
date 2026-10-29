"""In-memory columnar tables.

A :class:`Table` holds one Python list per column, all of the same length,
plus the :class:`~tsarc.schema.Schema` describing them.  Values are always in
canonical form (see :func:`tsarc.types.coerce`): constructing or appending
validates every value.

Equality (``==``) is exact: floats compare by bit pattern, so a NaN equals
itself and ``0.0`` differs from ``-0.0``.  This is what round-trip tests want.
"""
from . import types as T
from .errors import SchemaError
from .schema import Schema


class Table:
    __slots__ = ("_schema", "_cols")

    def __init__(self, schema, columns=None, *, validate=True):
        if not isinstance(schema, Schema):
            schema = Schema(schema)
        self._schema = schema
        if columns is None:
            self._cols = [[] for _ in schema]
            return
        if isinstance(columns, dict):
            missing = [n for n in schema.names if n not in columns]
            extra = [n for n in columns if n not in schema]
            if missing:
                raise SchemaError(f"missing column data for {', '.join(missing)}")
            if extra:
                raise SchemaError(f"data for unknown columns {', '.join(extra)}")
            cols = [list(columns[n]) for n in schema.names]
        else:
            cols = [list(c) for c in columns]
            if len(cols) != len(schema):
                raise SchemaError(f"expected {len(schema)} columns of data, got {len(cols)}")
        lengths = {len(c) for c in cols}
        if len(lengths) > 1:
            detail = ", ".join(f"{c.name}={len(v)}" for c, v in zip(schema, cols))
            raise SchemaError(f"columns have different lengths ({detail})")
        if validate:
            for c, values in zip(schema, cols):
                for i, v in enumerate(values):
                    values[i] = c.coerce(v, i)
        self._cols = cols

    # -- construction -------------------------------------------------------------------------

    @classmethod
    def empty(cls, schema):
        return cls(schema)

    @classmethod
    def from_rows(cls, schema, rows):
        """Build a table from an iterable of tuples (schema order) or dicts (by name)."""
        t = cls(schema)
        t.extend(rows)
        return t

    @classmethod
    def concat(cls, tables):
        tables = list(tables)
        if not tables:
            raise SchemaError("concat needs at least one table")
        schema = tables[0].schema
        for t in tables[1:]:
            if t.schema != schema:
                raise SchemaError(f"cannot concatenate tables with different schemas: "
                                  f"{schema.to_text()} vs {t.schema.to_text()}")
        cols = [[] for _ in schema]
        for t in tables:
            for dst, src in zip(cols, t._cols):
                dst.extend(src)
        return cls._trusted(schema, cols)

    @classmethod
    def _trusted(cls, schema, cols):
        t = cls.__new__(cls)
        t._schema = schema
        t._cols = cols
        return t

    # -- basic access -------------------------------------------------------------------------

    @property
    def schema(self):
        return self._schema

    @property
    def num_rows(self):
        return len(self._cols[0])

    @property
    def num_columns(self):
        return len(self._cols)

    def __len__(self):
        return self.num_rows

    def column(self, name):
        """A copy of one column's values."""
        return list(self._cols[self._schema.index(name)])

    def column_view(self, name):
        """The column's list itself (do not modify)."""
        return self._cols[self._schema.index(name)]

    def columns(self):
        """``{name: list}`` copies, in schema order."""
        return {c.name: list(v) for c, v in zip(self._schema, self._cols)}

    def time_values(self):
        return self._cols[0]

    def row(self, i):
        return tuple(col[i] for col in self._cols)

    def rows(self):
        return zip(*self._cols) if self._cols else iter(())

    def to_dicts(self):
        names = self._schema.names
        return [dict(zip(names, r)) for r in self.rows()]

    def __iter__(self):
        return iter(self.rows())

    def __eq__(self, other):
        if not isinstance(other, Table) or other._schema != self._schema:
            return False
        if other.num_rows != self.num_rows:
            return False
        for c, a, b in zip(self._schema, self._cols, other._cols):
            for x, y in zip(a, b):
                if not T.values_equal(c.type, x, y):
                    return False
        return True

    def __repr__(self):
        return f"Table({self._schema.to_text()!r}, rows={self.num_rows})"

    # -- mutation -----------------------------------------------------------------------------

    def append(self, row):
        """Append one row: a tuple in schema order or a dict keyed by column name."""
        if isinstance(row, dict):
            unknown = [k for k in row if k not in self._schema]
            if unknown:
                raise SchemaError(f"row has unknown columns {', '.join(map(str, unknown))}")
            try:
                values = [row[n] for n in self._schema.names]
            except KeyError as exc:
                raise SchemaError(f"row is missing column {exc.args[0]!r}") from None
        else:
            values = list(row)
            if len(values) != len(self._schema):
                raise SchemaError(f"row has {len(values)} values, schema has {len(self._schema)} "
                                  f"columns")
        n = self.num_rows
        coerced = [c.coerce(v, n) for c, v in zip(self._schema, values)]
        for col, v in zip(self._cols, coerced):
            col.append(v)

    def extend(self, rows):
        for r in rows:
            self.append(r)

    # -- derivation ---------------------------------------------------------------------------

    def take(self, indices):
        indices = list(indices)
        return Table._trusted(self._schema, [[col[i] for i in indices] for col in self._cols])

    def slice(self, start=0, stop=None):
        return Table._trusted(self._schema, [col[start:stop] for col in self._cols])

    def head(self, n):
        return self.slice(0, max(n, 0))

    def tail(self, n):
        if n <= 0:
            return self.slice(0, 0)
        return self.slice(max(self.num_rows - n, 0))

    def filter(self, mask):
        mask = list(mask)
        if len(mask) != self.num_rows:
            raise ValueError(f"mask has {len(mask)} entries for {self.num_rows} rows")
        return self.take(i for i, keep in enumerate(mask) if keep)

    def select(self, names):
        sub = self._schema.select(names)
        return Table._trusted(sub, [list(self._cols[self._schema.index(c.name)]) for c in sub])

    def sort_by(self, names=None, descending=False):
        """Stable sort by the given columns (default: the time column)."""
        if names is None:
            names = [self._schema.time_column.name]
        elif isinstance(names, str):
            names = [names]
        idx = [self._schema.index(n) for n in names]
        types = [self._schema[i].type for i in idx]

        def key(i):
            return tuple(T.sort_key(t, self._cols[j][i]) for t, j in zip(types, idx))

        order = sorted(range(self.num_rows), key=key, reverse=descending)
        return self.take(order)

    def is_time_sorted(self):
        ts = self._cols[0]
        return all(ts[i] <= ts[i + 1] for i in range(len(ts) - 1))

    def rename(self, mapping):
        return Table._trusted(self._schema.renamed(mapping), [list(c) for c in self._cols])

    def drop(self, name):
        sub = self._schema.without(name)
        return Table._trusted(sub, [list(self._cols[self._schema.index(c.name)]) for c in sub])

    def with_column(self, column, values):
        values = list(values)
        if len(values) != self.num_rows:
            raise SchemaError(f"new column has {len(values)} values for {self.num_rows} rows")
        schema = self._schema.with_column(column)
        coerced = [column.coerce(v, i) for i, v in enumerate(values)]
        return Table._trusted(schema, [list(c) for c in self._cols] + [coerced])

    def time_range(self):
        """``(min, max)`` of the time column, or None for an empty table."""
        ts = self._cols[0]
        if not ts:
            return None
        return min(ts), max(ts)
