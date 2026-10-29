"""Schemas: the ordered, typed columns of an archive.

The first column of every schema is the *time column*: it has type ``ts`` and
every row must have a value in it.  Range queries, resampling, merging and
the range shown by ``info`` all work on the time column.

Text form (used by the CLI, CSV headers and ``Schema.parse``)::

    ts:ts,temp:float,site:str
"""
import re
from dataclasses import dataclass

from . import types as T
from .errors import SchemaError

NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
MAX_COLUMNS = 1024


def check_column_name(name):
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise SchemaError(
            f"bad column name {name!r}: use letters, digits and '_', not starting with a digit, "
            f"at most 64 characters"
        )
    return name


@dataclass(frozen=True)
class Column:
    """One column: a name and a value type (see :mod:`tsarc.types`)."""

    name: str
    type: str

    def __post_init__(self):
        check_column_name(self.name)
        T.check_type_name(self.type)

    def to_text(self):
        return f"{self.name}:{self.type}"

    @classmethod
    def parse(cls, text):
        """Parse ``name:type``."""
        t = text.strip()
        if ":" not in t:
            raise SchemaError(f"column spec {text!r} must look like name:type")
        name, type_ = t.split(":", 1)
        return cls(name.strip(), type_.strip())

    def coerce(self, value, row=None):
        what = self.name if row is None else f"{self.name}[{row}]"
        return T.coerce(self.type, value, what)


class Schema:
    """An immutable ordered collection of columns with unique names."""

    __slots__ = ("_columns", "_index")

    def __init__(self, columns):
        cols = []
        for c in columns:
            if isinstance(c, Column):
                cols.append(c)
            elif isinstance(c, str):
                cols.append(Column.parse(c))
            else:
                name, type_ = c
                cols.append(Column(name, type_))
        if not cols:
            raise SchemaError("a schema needs at least one column")
        if len(cols) > MAX_COLUMNS:
            raise SchemaError(f"too many columns ({len(cols)} > {MAX_COLUMNS})")
        if cols[0].type != T.TS:
            raise SchemaError(f"the first column must have type ts (the time column), got "
                              f"{cols[0].to_text()}")
        index = {}
        for i, c in enumerate(cols):
            if c.name in index:
                raise SchemaError(f"duplicate column name {c.name!r}")
            index[c.name] = i
        self._columns = tuple(cols)
        self._index = index

    # -- construction -------------------------------------------------------------------------

    @classmethod
    def parse(cls, text):
        parts = [p for p in text.split(",") if p.strip()]
        return cls([Column.parse(p) for p in parts])

    def to_text(self):
        return ",".join(c.to_text() for c in self._columns)

    # -- access -------------------------------------------------------------------------------

    @property
    def columns(self):
        return self._columns

    @property
    def names(self):
        return [c.name for c in self._columns]

    @property
    def time_column(self):
        return self._columns[0]

    def __len__(self):
        return len(self._columns)

    def __iter__(self):
        return iter(self._columns)

    def __contains__(self, name):
        return name in self._index

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._columns[key]
        return self.column(key)

    def column(self, name):
        try:
            return self._columns[self._index[name]]
        except KeyError:
            raise SchemaError(f"no column named {name!r} (columns: {', '.join(self.names)})") from None

    def index(self, name):
        self.column(name)
        return self._index[name]

    def __eq__(self, other):
        return isinstance(other, Schema) and self._columns == other._columns

    def __hash__(self):
        return hash(self._columns)

    def __repr__(self):
        return f"Schema({self.to_text()!r})"

    # -- derivation ---------------------------------------------------------------------------

    def select(self, names):
        """A schema with only ``names``, in the given order.  The time column is kept first
        even when it is not named."""
        names = list(names)
        for n in names:
            self.column(n)
        tname = self.time_column.name
        ordered = [tname] + [n for n in names if n != tname]
        seen = set()
        out = []
        for n in ordered:
            if n not in seen:
                seen.add(n)
                out.append(self.column(n))
        return Schema(out)

    def with_column(self, column):
        if column.name in self._index:
            raise SchemaError(f"column {column.name!r} already exists")
        return Schema(list(self._columns) + [column])

    def without(self, name):
        if name == self.time_column.name:
            raise SchemaError("the time column cannot be removed")
        self.column(name)
        return Schema([c for c in self._columns if c.name != name])

    def renamed(self, mapping):
        out = []
        for c in self._columns:
            new = mapping.get(c.name, c.name)
            out.append(Column(new, c.type))
        return Schema(out)

    def describe(self):
        """Lines ``name  type`` aligned for display."""
        width = max(len(c.name) for c in self._columns)
        return [f"{c.name.ljust(width)}  {c.type}" for c in self._columns]
