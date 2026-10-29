"""Comparing two tables row by row."""
from dataclasses import dataclass, field

from . import types as T


@dataclass
class TableDiff:
    schema_equal: bool
    left_rows: int
    right_rows: int
    differing_rows: list = field(default_factory=list)   # (row index, [column names])
    schema_text: tuple = ("", "")

    @property
    def equal(self):
        return self.schema_equal and self.left_rows == self.right_rows and not self.differing_rows

    def lines(self, limit=10):
        if self.equal:
            return ["identical"]
        out = []
        if not self.schema_equal:
            out.append(f"schema differs: {self.schema_text[0]} vs {self.schema_text[1]}")
            return out
        if self.left_rows != self.right_rows:
            out.append(f"row count differs: {self.left_rows} vs {self.right_rows}")
        for i, cols in self.differing_rows[:limit]:
            out.append(f"row {i}: {', '.join(cols)}")
        more = len(self.differing_rows) - limit
        if more > 0:
            out.append(f"... and {more} more differing rows")
        return out


def diff_tables(left, right):
    d = TableDiff(left.schema == right.schema, left.num_rows, right.num_rows,
                  schema_text=(left.schema.to_text(), right.schema.to_text()))
    if not d.schema_equal:
        return d
    n = min(left.num_rows, right.num_rows)
    cols = list(left.schema)
    for i in range(n):
        bad = [c.name for c in cols
               if not T.values_equal(c.type, left.column_view(c.name)[i], right.column_view(c.name)[i])]
        if bad:
            d.differing_rows.append((i, bad))
    return d
