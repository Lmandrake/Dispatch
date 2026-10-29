import math

import pytest

from tsarc import ExpressionError, Schema, Table
from tsarc.expr import compile_expression
from tsarc.fill import fill_table
from tsarc.ops import dedupe, find_gaps, merge_tables, resample, rolling, every_nth, reservoir
from tsarc.ops.derive import derive

from .helpers import SEC, T0, weather


def mask(expr, t):
    return compile_expression(expr, t.schema).mask(t)


def test_expr_basic():
    t = weather(30)
    m = mask("site = 'roof' and hum >= 50", t)
    assert m == [r["site"] == "roof" and r["hum"] >= 50 for r in t.to_dicts()]
    assert sum(mask("ts >= '2026-03-01T00:10:00Z'", t)) == 20
    assert sum(mask("site in ('roof', 'lab')", t)) == 20
    assert sum(mask("isnan(temp)", t)) == 1
    assert sum(mask("hour(ts) = 0 and minute(ts) between 5 and 9", t)) == 5
    assert sum(mask("site ~ '^r'", t)) == 10
    assert sum(mask("not (hum % 2 = 0)", t)) == sum(1 for h in t.column("hum") if h % 2)


@pytest.mark.parametrize("bad,pos", [("hum >", 5), ("site = ", 7), ("nosuch > 1", 0),
                                     ("site > 1", 5), ("hum + 'x' > 1", 4), ("(hum > 1", 8)])
def test_expr_errors(bad, pos):
    with pytest.raises(ExpressionError) as ei:
        mask(bad, weather(3))
    assert ei.value.position == pos


def test_resample():
    t = weather(30)
    r = resample(t, 10 * 60 * SEC, {"hum": ["mean", "count"], "temp": "max"})
    assert r.schema.to_text() == "ts:ts,hum_mean:float,hum_count:int,temp_max:float"
    assert r.num_rows == 3
    assert r.column("hum_count") == [10, 10, 10]
    assert r.column("ts") == [T0, T0 + 600 * SEC, T0 + 1200 * SEC]


def test_merge_and_dedupe():
    a = weather(5)
    m = merge_tables([a, a])
    assert m.num_rows == 10 and m.is_time_sorted()
    assert dedupe(m) == a


def test_rolling_and_gaps():
    t = weather(10)
    r = rolling(t, "hum", 3 * 60 * SEC, "count")
    assert r.column("hum_rolling_count") == [1, 2, 3, 3, 3, 3, 3, 3, 3, 3]
    s = Schema.parse("ts:ts")
    g = find_gaps(Table.from_rows(s, [(0,), (10,), (100,), (105,)]), 20)
    assert [(x.start, x.end) for x in g] == [(10, 100)]


def test_fill():
    s = Schema.parse("ts:ts,x:float")
    t = Table.from_rows(s, [(0, 1.0), (1, math.nan), (3, 5.0), (4, math.nan)])
    assert fill_table(t, method="forward").column("x") == [1.0, 1.0, 5.0, 5.0]
    assert fill_table(t, method="linear").column("x")[1] == pytest.approx(7 / 3)


def test_sample_and_derive():
    t = weather(20)
    assert every_nth(t, 5).num_rows == 4
    assert reservoir(t, 5, seed=1) == reservoir(t, 5, seed=1)
    d = derive(t, "hum2", "hum * 2")
    assert d.column("hum2") == [h * 2 for h in t.column("hum")]
    assert d.schema.column("hum2").type == "int"
