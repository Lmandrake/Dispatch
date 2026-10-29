"""Data-quality checks (``tsarc check``).

Each check returns a list of :class:`Finding`.  Rules for value ranges come
from a small text file, one rule per line::

    # comments and blank lines are ignored
    temp  -60 .. 60
    hum   0 .. 100
    site  in roof, yard, lab

Numeric rules are inclusive; NaN never satisfies a numeric rule.
"""
import math
from dataclasses import dataclass

from . import types as T
from .errors import QueryError
from .timeutil import format_duration, format_ts


@dataclass(frozen=True)
class Finding:
    check: str
    row: object      # 0-based row index, or None for a whole-table finding
    message: str

    def line(self):
        where = "table" if self.row is None else f"row {self.row}"
        return f"{self.check}: {where}: {self.message}"


@dataclass(frozen=True)
class RangeRule:
    column: str
    low: object = None
    high: object = None
    allowed: tuple = ()

    def violates(self, type_, value):
        if self.allowed:
            return T.format_text(type_, value) not in self.allowed
        if isinstance(value, float) and math.isnan(value):
            return True
        if self.low is not None and value < self.low:
            return True
        if self.high is not None and value > self.high:
            return True
        return False

    def describe(self):
        if self.allowed:
            return f"in {', '.join(self.allowed)}"
        lo = "" if self.low is None else repr(self.low)
        hi = "" if self.high is None else repr(self.high)
        return f"{lo} .. {hi}"


def parse_rules(text):
    rules = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise QueryError(f"rules line {lineno}: expected '<column> <rule>'")
        column, rule = parts
        rule = rule.strip()
        if rule.startswith("in "):
            allowed = tuple(v.strip() for v in rule[3:].split(",") if v.strip())
            if not allowed:
                raise QueryError(f"rules line {lineno}: empty 'in' list")
            rules.append(RangeRule(column, allowed=allowed))
            continue
        if ".." not in rule:
            raise QueryError(f"rules line {lineno}: expected 'low .. high' or 'in a, b'")
        lo_text, hi_text = (p.strip() for p in rule.split("..", 1))
        try:
            lo = float(lo_text) if lo_text else None
            hi = float(hi_text) if hi_text else None
        except ValueError:
            raise QueryError(f"rules line {lineno}: bad number") from None
        if lo is not None and hi is not None and hi < lo:
            raise QueryError(f"rules line {lineno}: high is below low")
        rules.append(RangeRule(column, lo, hi))
    return rules


def check_sorted(table):
    ts = table.time_values()
    out = []
    for i in range(1, len(ts)):
        if ts[i] < ts[i - 1]:
            out.append(Finding("order", i, f"time goes backwards ({format_ts(ts[i])} after "
                                           f"{format_ts(ts[i - 1])})"))
    return out


def check_duplicate_times(table):
    seen = {}
    out = []
    for i, t in enumerate(table.time_values()):
        if t in seen:
            out.append(Finding("duplicate-time", i, f"same time as row {seen[t]} ({format_ts(t)})"))
        else:
            seen[t] = i
    return out


def check_nan(table):
    out = []
    for c in table.schema:
        if c.type != T.FLOAT:
            continue
        n = sum(1 for v in table.column_view(c.name) if isinstance(v, float) and math.isnan(v))
        if n:
            out.append(Finding("nan", None, f"column {c.name!r} has {n} NaN values"))
    return out


def check_gaps(table, threshold):
    from .ops.gaps import find_gaps

    return [Finding("gap", g.rows_before, f"{format_duration(g.length)} gap after "
                                          f"{format_ts(g.start)}")
            for g in find_gaps(table, threshold)]


def check_rules(table, rules):
    out = []
    for rule in rules:
        if rule.column not in table.schema:
            raise QueryError(f"rule for unknown column {rule.column!r}")
        col = table.schema.column(rule.column)
        if not rule.allowed and col.type not in (T.INT, T.FLOAT):
            raise QueryError(f"numeric rule for {col.type} column {col.name!r}")
        for i, v in enumerate(table.column_view(col.name)):
            if v is None:
                continue
            if rule.violates(col.type, v):
                out.append(Finding("range", i, f"{col.name} = {T.format_text(col.type, v)} not "
                                               f"{rule.describe()}"))
    return out


def run_checks(table, rules=(), gap_threshold=None):
    findings = []
    findings += check_sorted(table)
    findings += check_duplicate_times(table)
    findings += check_nan(table)
    if gap_threshold is not None:
        findings += check_gaps(table, gap_threshold)
    findings += check_rules(table, rules)
    return findings
