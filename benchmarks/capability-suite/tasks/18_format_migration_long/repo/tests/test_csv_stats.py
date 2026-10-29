import io
import math

import pytest

from tsarc import CsvImportError, Schema, Table
from tsarc import csvio, jsonio
from tsarc.stats import column_stats, render_stats, time_stats

from .helpers import T0, flags_table, weather


def test_csv_roundtrip():
    t = weather(30)
    text = csvio.table_to_csv_text(t)
    assert text.splitlines()[0] == "ts:ts,temp:float,hum:int,site:str"
    assert text.splitlines()[1] == "2026-03-01T00:00:00Z,15.0,40,roof"
    back = csvio.csv_to_table(text)
    assert back == t


def test_csv_bool_roundtrip():
    t = flags_table()
    assert csvio.csv_to_table(csvio.table_to_csv_text(t)) == t


def test_csv_inference():
    text = "time,a,b,c,d\n2026-03-01,1,1.5,x,true\n2026-03-01T00:00:01.5Z,2,2,y,no\n"
    t = csvio.csv_to_table(text)
    assert t.schema.to_text() == "time:ts,a:int,b:float,c:str,d:bool"
    assert t.column("time") == [T0, T0 + 1_500_000]


def test_csv_with_schema():
    t = csvio.csv_to_table("ts,v\n1,2\n", "ts:ts,v:float")
    assert t.column("v") == [2.0]
    assert t.column("ts") == [1_000_000]
    with pytest.raises(CsvImportError):
        csvio.csv_to_table("ts,w\n1,2\n", "ts:ts,v:float")


def test_csv_errors():
    with pytest.raises(CsvImportError) as ei:
        csvio.csv_to_table("ts:ts,v:int\n2026-03-01,1\n2026-03-01,x\n")
    assert ei.value.line == 3
    with pytest.raises(CsvImportError):
        csvio.csv_to_table("")
    with pytest.raises(CsvImportError) as ei:
        csvio.csv_to_table("ts:ts,v:int\n2026-03-01,1,2\n")
    assert ei.value.line == 2


def test_csv_special_floats():
    s = Schema.parse("ts:ts,x:float")
    t = Table.from_rows(s, [(1, math.nan), (2, math.inf), (3, -0.0)])
    text = csvio.table_to_csv_text(t)
    assert "nan" in text and "inf" in text and "-0.0" in text
    assert csvio.csv_to_table(text) == t


def test_jsonl():
    t = weather(3)
    buf = io.StringIO()
    jsonio.table_to_jsonl(t, buf)
    first = buf.getvalue().splitlines()[0]
    assert first == '{"ts":"2026-03-01T00:00:00Z","temp":15.0,"hum":40,"site":"roof"}'


def test_column_stats():
    t = weather(50)
    st = {s.name: s for s in column_stats(t)}
    assert st["temp"].nan == 2 and st["temp"].count == 50
    assert st["site"].distinct == 3
    assert st["hum"].min == 40
    assert st["ts"].min == T0


def test_render_stats():
    out = render_stats(weather(10))
    lines = out.splitlines()
    assert lines[0].split() == ["column", "type", "count", "min", "max", "mean", "notes"]
    assert lines[2].split()[:3] == ["ts", "ts", "10"]
    assert "distinct=3" in out


def test_time_stats():
    first, last, span, rate = time_stats(weather(11))
    assert span == 600.0 and rate == pytest.approx(10 / 600)
    assert time_stats(Table(Schema.parse("ts:ts"))) is None
