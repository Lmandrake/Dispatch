import math

import pytest

from tsarc import Schema, Table
from tsarc.compare import compare_tables, ks_statistic
from tsarc.lineproto import lines_to_table, table_to_lines
from tsarc.ops.window import ewma
from tsarc.rollup import bucket_label, bucket_start, rollup
from tsarc.store import Store

from .helpers import SEC, T0, weather


def test_lineproto_roundtrip():
    t = weather(5).drop("temp")
    lines = table_to_lines(t, "wx")
    assert lines[0] == f"wx,site=roof hum=40i {T0 * 1000}"
    back = lines_to_table("\n".join(lines))
    assert back.schema.to_text() == "ts:ts,hum:int,site:str"
    assert back.column("hum") == t.column("hum")


def test_lineproto_escapes_and_nan():
    s = Schema.parse("ts:ts,x:float,tag:str")
    t = Table.from_rows(s, [(1, math.nan, "a b"), (2, 1.5, "c,d")])
    lines = table_to_lines(t, "m 1")
    assert lines == ["m\\ 1,tag=c\\,d x=1.5 2000"]
    assert lines_to_table(lines[0]).column("tag") == ["c,d"]


def test_rollup_month_and_tz():
    s = Schema.parse("ts:ts,v:int")
    jan31_late = T0 - 3600 * SEC  # 2026-02-28T23:00Z
    t = Table.from_rows(s, [(jan31_late, 1), (T0, 2), (T0 + 86400 * SEC, 3)])
    r = rollup(t, "month", {"v": "sum"})
    assert r.column("v_sum") == [1, 5]
    r = rollup(t, "month", {"v": "sum"}, offset=2 * 3600 * SEC)
    assert r.column("v_sum") == [6]
    assert bucket_label(T0, "week") == "2026-W09"
    assert bucket_start(T0 + 5 * SEC, "day") == T0


def test_store(tmp_path):
    st = Store.create(tmp_path / "s", "ts:ts,temp:float,hum:int,site:str", {"a": "b"})
    t = weather(30, step=3600 * SEC)
    assert st.add(t) == {"2026-03-01": 24, "2026-03-02": 6}
    st.add(weather(2, step=3600 * SEC))
    assert [d for d, _, _ in st.stats()] == ["2026-03-01", "2026-03-02"]
    q = st.query(T0 + 20 * 3600 * SEC, T0 + 26 * 3600 * SEC)
    assert q.num_rows == 6 and q.is_time_sorted()
    assert Store(tmp_path / "s").query().num_rows == 32


def test_compare_and_ewma():
    a = weather(30)
    c = compare_tables(a, a)
    assert [x.name for x in c] == ["temp", "hum"]
    assert all(x.ks == 0.0 for x in c)
    assert ks_statistic([1, 2, 3], [4, 5, 6]) == 1.0
    s = Schema.parse("ts:ts,x:float")
    t = Table.from_rows(s, [(0, 0.0), (10, 10.0), (20, math.nan)])
    e = ewma(t, "x", 10).column("x_ewma")
    assert e == [0.0, 5.0, 5.0]
    with pytest.raises(Exception):
        ewma(t, "x", 0)
