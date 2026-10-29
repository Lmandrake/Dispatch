import math

from tsarc import Schema, Table, write_archive
from tsarc.manifest import check_manifest, write_manifest
from tsarc.ops.groupby import groupby
from tsarc.ops.outliers import find_outliers
from tsarc.quality import parse_rules, run_checks
from tsarc.spark import sparkline

from .helpers import weather


def test_groupby():
    names, rows = groupby(weather(30), "site", {"hum": ["min", "count"]})
    assert names == ["site", "hum_min", "hum_count", "rows"]
    assert [r["site"] for r in rows] == ["lab", "roof", "yard"]
    assert all(r["rows"] == 10 for r in rows)


def test_outliers():
    s = Schema.parse("ts:ts,x:float")
    t = Table.from_rows(s, [(i, 1.0 + (i % 3) * 0.1) for i in range(30)] + [(99, 50.0)])
    assert find_outliers(t, "x") == [30]


def test_quality():
    s = Schema.parse("ts:ts,x:float,site:str")
    t = Table.from_rows(s, [(0, 1.0, "a"), (0, math.nan, "b"), (-1, 200.0, "c")])
    rules = parse_rules("x 0 .. 100\nsite in a, b\n")
    lines = [f.line() for f in run_checks(t, rules)]
    assert "order: row 2: time goes backwards (1969-12-31T23:59:59.999999Z after " \
           "1970-01-01T00:00:00Z)" in lines
    assert "duplicate-time: row 1: same time as row 0 (1970-01-01T00:00:00Z)" in lines
    assert "range: row 2: x = 200.0 not 0.0 .. 100.0" in lines
    assert "range: row 2: site = c not in a, b" in lines


def test_sparkline():
    assert sparkline([0, 1, 2, 3, 4, 5, 6, 7]) == "▁▂▃▄▅▆▇█"
    assert sparkline([1.0, math.nan, 1.0]) == "▅ ▅"


def test_manifest(tmp_path):
    write_archive(tmp_path / "a.tsa", weather(5))
    write_manifest(tmp_path)
    assert check_manifest(tmp_path) == []
    write_archive(tmp_path / "a.tsa", weather(6))
    write_archive(tmp_path / "b.tsa", weather(6))
    assert check_manifest(tmp_path) == ["a.tsa: content changed", "b.tsa: not in manifest"]


def test_units():
    from tsarc.units import convert_column, convert_value

    assert abs(convert_value(100.0, "°C", "°F") - 212.0) < 1e-9
    assert abs(convert_value(1013.25, "hPa", "kPa") - 101.325) < 1e-12
    t, meta = convert_column(weather(3), {"units.temp": "°C"}, "temp", "K")
    assert meta == {"units.temp": "K"}
    assert t.column("temp")[0] == 15.0 + 273.15


def test_tz():
    from tsarc.tz import format_local, parse_offset

    off = parse_offset("+05:30")
    assert format_local(1_772_323_200_000_000, off) == "2026-03-01T05:30:00+05:30"
    assert parse_offset("Z") == 0


def test_reindex():
    from tsarc.ops.reindex import reindex

    s = Schema.parse("ts:ts,x:float")
    t = Table.from_rows(s, [(0, 0.0), (10, 10.0)])
    assert reindex(t, [5, 10, 20]).column("x")[:2] == [5.0, 10.0]
    assert math.isnan(reindex(t, [20]).column("x")[0])
    assert reindex(t, [4, 6], "nearest").column("x") == [0.0, 10.0]


def test_chart():
    from tsarc.chart import line_chart

    out = line_chart(weather(40), "hum", width=20, height=5)
    lines = out.splitlines()
    assert len(lines) == 7 and lines[0].startswith("85.5 |")
