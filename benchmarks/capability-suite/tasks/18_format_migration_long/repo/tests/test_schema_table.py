import math

import pytest

from tsarc import Column, Schema, SchemaError, Table

from .helpers import T0, weather


def test_schema_parse_roundtrip():
    s = Schema.parse("ts:ts, temp:float ,site:str")
    assert s.names == ["ts", "temp", "site"]
    assert s.to_text() == "ts:ts,temp:float,site:str"
    assert Schema.parse(s.to_text()) == s


@pytest.mark.parametrize("text", ["temp:float", "ts:ts,ts:int", "ts:ts,9x:int", "ts:ts,a:complex",
                                  "ts:ts,a"])
def test_schema_rejects(text):
    with pytest.raises(SchemaError):
        Schema.parse(text)


def test_schema_select_keeps_time_first():
    s = Schema.parse("ts:ts,a:int,b:str")
    assert s.select(["b"]).names == ["ts", "b"]
    assert s.select(["b", "ts", "a"]).names == ["ts", "b", "a"]


def test_schema_describe():
    s = Schema.parse("ts:ts,temperature:float")
    assert s.describe() == ["ts           ts", "temperature  float"]


def test_column_coerce():
    c = Column("x", "float")
    assert c.coerce(3) == 3.0 and isinstance(c.coerce(3), float)
    with pytest.raises(SchemaError):
        c.coerce(True)
    with pytest.raises(SchemaError):
        Column("n", "int").coerce(2 ** 63)
    with pytest.raises(SchemaError):
        Column("s", "str").coerce(None)


def test_table_from_rows_and_dicts():
    s = Schema.parse("ts:ts,v:int")
    t = Table.from_rows(s, [(1, 2), {"ts": 3, "v": 4}])
    assert t.num_rows == 2
    assert t.column("v") == [2, 4]
    assert t.to_dicts() == [{"ts": 1, "v": 2}, {"ts": 3, "v": 4}]


def test_table_rejects_bad_rows():
    s = Schema.parse("ts:ts,v:int")
    t = Table(s)
    with pytest.raises(SchemaError):
        t.append((1,))
    with pytest.raises(SchemaError):
        t.append({"ts": 1})
    with pytest.raises(SchemaError):
        t.append((1, None))
    assert t.num_rows == 0


def test_table_equality_is_exact():
    s = Schema.parse("ts:ts,x:float")
    a = Table.from_rows(s, [(1, math.nan), (2, 0.0)])
    b = Table.from_rows(s, [(1, math.nan), (2, 0.0)])
    c = Table.from_rows(s, [(1, math.nan), (2, -0.0)])
    assert a == b
    assert a != c


def test_table_ops():
    t = weather(10)
    assert t.head(3).num_rows == 3
    assert t.tail(2).column("ts") == t.column("ts")[-2:]
    assert t.select(["site"]).schema.names == ["ts", "site"]
    assert t.sort_by("hum").column("hum") == sorted(t.column("hum"))
    assert t.time_range() == (T0, T0 + 9 * 60_000_000)
    assert t.drop("site").schema.names == ["ts", "temp", "hum"]
    assert Table.concat([t, t]).num_rows == 20
