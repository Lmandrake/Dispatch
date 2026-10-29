import math
import struct
from pathlib import Path

import pytest

from tsarc import (ArchiveReader, ArchiveWriter, ChecksumError, FormatError, NotRepresentableError,
                   Schema, Table, UnsupportedVersionError, append_rows, convert, open_archive,
                   read_table, set_metadata, write_archive)

from .helpers import T0, flags_table, weather

DATA = Path(__file__).parent / "data"


def test_roundtrip_default(tmp_path):
    t = weather()
    p = tmp_path / "w.tsa"
    assert write_archive(p, t, {"source": "lab", "units.temp": "°C"}) == 50
    rd = open_archive(p)
    assert rd.version == 2
    assert rd.table == t
    assert rd.metadata == {"source": "lab", "units.temp": "°C"}
    assert list(rd.metadata) == ["source", "units.temp"]
    assert rd.num_rows == 50
    assert rd.time_range() == (T0, T0 + 49 * 60_000_000)


def test_roundtrip_v1(tmp_path):
    t = weather()
    p = tmp_path / "w1.tsa"
    write_archive(p, t, version=1)
    rd = ArchiveReader(p)
    assert rd.version == 1 and rd.metadata == {} and rd.table == t


def test_v1_not_representable(tmp_path):
    p = tmp_path / "x.tsa"
    with pytest.raises(NotRepresentableError) as ei:
        write_archive(p, flags_table(), version=1)
    assert ei.value.column == "ok"
    assert not p.exists()
    with pytest.raises(NotRepresentableError):
        write_archive(p, weather(), {"a": "b"}, version=1)
    s = Schema.parse("ts:ts,s:str")
    with pytest.raises(NotRepresentableError) as ei:
        write_archive(p, Table.from_rows(s, [(1, "ok"), (2, "日本")]), version=1)
    assert (ei.value.column, ei.value.row) == ("s", 1)


def test_failed_write_leaves_existing_file(tmp_path):
    p = tmp_path / "x.tsa"
    write_archive(p, weather(5))
    before = p.read_bytes()
    with pytest.raises(NotRepresentableError):
        write_archive(p, flags_table(), version=1)
    assert p.read_bytes() == before
    assert sorted(x.name for x in tmp_path.iterdir()) == ["x.tsa"]


def test_unknown_version(tmp_path):
    with pytest.raises(UnsupportedVersionError):
        write_archive(tmp_path / "x.tsa", weather(), version=9)
    p = tmp_path / "y.tsa"
    p.write_bytes(b"TSAR" + struct.pack("<H", 7) + b"\0" * 40)
    with pytest.raises(UnsupportedVersionError) as ei:
        ArchiveReader(p)
    assert ei.value.version == 7


def test_bad_magic(tmp_path):
    p = tmp_path / "x.tsa"
    p.write_bytes(b"NOPE" + b"\0" * 30)
    with pytest.raises(FormatError):
        ArchiveReader(p)


def test_fixtures_read():
    for name in ("weather_v1.tsa", "weather_v2.tsa"):
        rd = ArchiveReader(DATA / name)
        assert rd.num_rows == 300
        assert rd.schema.names[:3] == ["ts", "temp", "pressure"]
    assert ArchiveReader(DATA / "weather_v2.tsa").metadata["station"] == "Mt Wilson"
    assert ArchiveReader(DATA / "weather_v1.tsa").table == \
        ArchiveReader(DATA / "weather_v2.tsa").table.drop("ok")


@pytest.mark.parametrize("name,version", [("weather_v1.tsa", 1), ("weather_v2.tsa", 2),
                                          ("empty_v2.tsa", 2)])
def test_fixture_rewrite_identical(tmp_path, name, version):
    src = DATA / name
    rd = ArchiveReader(src)
    out = tmp_path / "copy.tsa"
    write_archive(out, rd.table, rd.metadata, version=version)
    assert out.read_bytes() == src.read_bytes()


def test_v2_checksums(tmp_path):
    data = bytearray((DATA / "weather_v2.tsa").read_bytes())
    data[-30] ^= 0x40
    p = tmp_path / "bad.tsa"
    p.write_bytes(bytes(data))
    with pytest.raises(ChecksumError):
        ArchiveReader(p)


def test_v1_checksum(tmp_path):
    data = bytearray((DATA / "weather_v1.tsa").read_bytes())
    data[100] ^= 0x01
    p = tmp_path / "bad.tsa"
    p.write_bytes(bytes(data))
    with pytest.raises(ChecksumError):
        ArchiveReader(p)


def test_query(tmp_path):
    t = weather(100)
    p = tmp_path / "w.tsa"
    write_archive(p, t)
    rd = ArchiveReader(p)
    q = rd.query(T0 + 60_000_000 * 10, T0 + 60_000_000 * 20)
    assert q.num_rows == 10
    assert q.column("ts")[0] == T0 + 600_000_000
    q2 = rd.query(columns=["site"], where="site = 'roof' and hum > 50")
    assert q2.schema.names == ["ts", "site"]
    assert all(s == "roof" for s in q2.column("site"))
    full = [r for r in t.to_dicts() if r["site"] == "roof" and r["hum"] > 50]
    assert q2.num_rows == len(full)


def test_append_and_convert(tmp_path):
    p = tmp_path / "w.tsa"
    write_archive(p, weather(10), {"k": "v"})
    assert append_rows(p, weather(5)) == 15
    rd = ArchiveReader(p)
    assert rd.num_rows == 15 and rd.metadata == {"k": "v"}
    q = tmp_path / "w1.tsa"
    write_archive(q, weather(10), version=1)
    assert convert(q, tmp_path / "w2.tsa", 2) == 10
    assert ArchiveReader(tmp_path / "w2.tsa").version == 2


def test_set_metadata(tmp_path):
    p = tmp_path / "w.tsa"
    write_archive(p, weather(3), {"a": "1"})
    assert set_metadata(p, [("b", "2")], ["a"]) == {"b": "2"}
    assert ArchiveReader(p).metadata == {"b": "2"}


def test_writer(tmp_path):
    p = tmp_path / "w.tsa"
    with ArchiveWriter(p, "ts:ts,temp:float,hum:int,site:str", {"x": "y"}) as w:
        w.write_table(weather(5))
        w.write_row((T0 + 10 ** 9, 1.0, 2, "z"))
    assert read_table(p).num_rows == 6
    q = tmp_path / "never.tsa"
    with pytest.raises(RuntimeError):
        with ArchiveWriter(q, "ts:ts,v:int") as w:
            w.write_row((1, 2))
            raise RuntimeError("boom")
    assert not q.exists()


def test_special_floats_roundtrip(tmp_path):
    s = Schema.parse("ts:ts,x:float")
    vals = [math.inf, -math.inf, math.nan, -0.0, 0.0, 5e-324, 1.7976931348623157e308]
    t = Table.from_rows(s, [(i, v) for i, v in enumerate(vals)])
    for version in (1, 2):
        p = tmp_path / f"s{version}.tsa"
        write_archive(p, t, version=version)
        assert read_table(p) == t


def test_extreme_ints(tmp_path):
    s = Schema.parse("ts:ts,n:int")
    t = Table.from_rows(s, [(-(2 ** 63), 2 ** 63 - 1), (2 ** 63 - 1, -(2 ** 63)), (0, 0)])
    p = tmp_path / "e.tsa"
    write_archive(p, t)
    assert read_table(p) == t
