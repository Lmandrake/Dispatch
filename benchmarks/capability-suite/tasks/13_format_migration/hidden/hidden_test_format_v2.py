import json
import math
import struct
import zlib
from pathlib import Path

import pytest

import senslog
from senslog import (CorruptFileError, LogReader, Record, SenslogError, UnsupportedVersionError,
                     read_records, write_log)
from senslog import csvio, ops, stats
from senslog.cli import main
from senslog.timefmt import format_ts, parse_ts

# looked up softly so that a missing name fails the tests that need it, not the whole module
NotRepresentableError = getattr(senslog, "NotRepresentableError", None)
migrate = getattr(senslog, "migrate", None)

HERE = Path(__file__).parent
V1 = HERE / "fixture_v1_station.slog"
V1_EMPTY = HERE / "fixture_v1_empty.slog"
US = 1_000_000


def crc(b):
    return zlib.crc32(b) & 0xFFFFFFFF


def key(r):
    v = ("f", struct.pack("<d", r.value)) if isinstance(r.value, float) else ("i", r.value)
    return (r.sensor, r.timestamp, v, r.label, r.calibrated, r.quality)


def expected_fixture():
    d = json.loads((HERE / "fixture_v1_station.json").read_text(encoding="utf-8"))
    recs = []
    for s, ts, v, lab, cal in d["records"]:
        val = float.fromhex(v["float"]) if "float" in v else v["int"]
        recs.append(Record(s, ts * US, val, lab, cal))
    return d["station"], d["created"] * US, recs


# --- independent v2 encoder, written from docs/FORMAT_v2.md ----------------------------------

def s16(t):
    b = t.encode("utf-8")
    return struct.pack("<H", len(b)) + b


def spec_v2(records, station, created, bs):
    h = struct.pack("<4sHHqIII", b"SLOG", 2, 0, created, len(records),
                    (len(records) + bs - 1) // bs, bs) + s16(station)
    out = bytearray(h + struct.pack("<I", crc(h)))
    idx = b""
    for i in range(0, len(records), bs):
        ch = records[i:i + bs]
        pl = b""
        for r in ch:
            if isinstance(r.value, float):
                kind, vb = 1, struct.pack("<d", r.value)
            else:
                kind, vb = 0, struct.pack("<q", r.value)
            pl += struct.pack("<HBBBq", r.sensor, kind, int(r.calibrated), r.quality, r.timestamp) + vb + s16(r.label)
        blk = struct.pack("<II", len(ch), len(pl)) + pl
        ts = [r.timestamp for r in ch]
        idx += struct.pack("<QIIqq", len(out), i, len(ch), min(ts), max(ts))
        out += blk + struct.pack("<I", crc(blk))
    off = len(out)
    out += idx + struct.pack("<QII4s", off, (len(records) + bs - 1) // bs, crc(idx), b"GOLS")
    return bytes(out)


def golden_recs():
    return [
        Record(7, 1_700_000_000_000_001, 1.5, "a", True, 90),
        Record(65535, -5, -2, "", False, 100),
        Record(1, 1_700_000_001_000_000, 3, "日", False, 0),
    ]
GOLDEN_HEX = (
    "534c4f470200000040222018240a060003000000020000000200000003005ac3a9dbdde640020000002f000000"
    "070001015a01401e18240a0600000000000000f83f010061ffff000064fbfffffffffffffffeffffffffffffff"
    "000021794ee4010000001a000000010000000040822d18240a060003000000000000000300e697a5ab9a6d8b25"
    "000000000000000000000002000000fbffffffffffffff01401e18240a06006000000000000000020000000100"
    "000040822d18240a060040822d18240a060086000000000000000200000070dac1d8474f4c53"
)
EMPTY_HEX = ("534c4f470200000000000000000000000000000000000000000100000000f59b0e9f"
             "22000000000000000000000000000000474f4c53")


# --- golden bytes ------------------------------------------------------------------------------

def test_golden_v2_bytes(tmp_path):
    p = tmp_path / "g.slog"
    assert write_log(p, golden_recs(), station="Zé", created=1_700_000_000_123_456, block_size=2) == 3
    assert p.read_bytes().hex() == GOLDEN_HEX


def test_golden_empty_v2(tmp_path):
    p = tmp_path / "e.slog"
    write_log(p, [], station="", created=0)
    assert p.read_bytes().hex() == EMPTY_HEX
    rd = LogReader(p)
    assert rd.version == 2 and rd.records == [] and rd.block_count == 0


def test_golden_reads_back(tmp_path):
    p = tmp_path / "g.slog"
    p.write_bytes(bytes.fromhex(GOLDEN_HEX))
    rd = LogReader(p)
    assert rd.version == 2
    assert rd.station == "Zé"
    assert rd.created == 1_700_000_000_123_456
    assert rd.block_count == 2
    assert rd.records == golden_recs()


def test_default_is_v2_block_256(tmp_path):
    recs = [Record(i % 5, i * 1500, float(i), "L" * (i % 7), i % 3 == 0, i % 101) for i in range(600)]
    p = tmp_path / "d.slog"
    write_log(p, recs, station="north", created=42)
    assert p.read_bytes() == spec_v2(recs, "north", 42, 256)
    rd = LogReader(p)
    assert rd.block_count == 3 and rd.records == recs


@pytest.mark.parametrize("bs", [1, 7, 256, 1000])
def test_migrate_fixture_matches_spec(tmp_path, bs):
    station, created, recs = expected_fixture()
    out = tmp_path / "m.slog"
    assert migrate(V1, out, block_size=bs) == 600
    assert out.read_bytes() == spec_v2(recs, station, created, bs)


def test_migrate_default_block_size(tmp_path):
    station, created, recs = expected_fixture()
    out = tmp_path / "m.slog"
    migrate(str(V1), str(out))
    assert out.read_bytes() == spec_v2(recs, station, created, 256)
    rd = LogReader(out)
    assert [key(r) for r in rd.records] == [key(r) for r in recs]


# --- v1 compatibility ------------------------------------------------------------------------

def test_read_v1_upconverts():
    station, created, recs = expected_fixture()
    rd = LogReader(V1)
    assert rd.version == 1 and rd.block_count is None
    assert rd.station == station and rd.created == created
    assert [key(r) for r in rd.records] == [key(r) for r in recs]
    assert all(r.quality == 100 for r in rd.records)
    assert rd.records[20].timestamp % US == 0 and rd.records[20].timestamp > 10 ** 15


def test_v1_rewrite_byte_exact(tmp_path):
    for src in (V1, V1_EMPTY):
        rd = LogReader(src)
        out = tmp_path / ("o" + src.name)
        write_log(out, rd.records, station=rd.station, created=rd.created, version=1)
        assert out.read_bytes() == src.read_bytes()


def test_v2_to_v1_roundtrip_exact(tmp_path):
    mid = tmp_path / "mid.slog"
    migrate(V1, mid, block_size=50)
    rd = LogReader(mid)
    back = tmp_path / "back.slog"
    write_log(back, rd.records, station=rd.station, created=rd.created, version=1)
    assert back.read_bytes() == V1.read_bytes()


def test_migrate_empty_v1(tmp_path):
    out = tmp_path / "e2.slog"
    assert migrate(V1_EMPTY, out) == 0
    rd = LogReader(out)
    assert rd.version == 2 and rd.station == "spare" and rd.created == 1_600_000_000 * US
    assert rd.block_count == 0 and rd.records == []


def test_migrate_v2_source(tmp_path):
    a = tmp_path / "a.slog"
    write_log(a, golden_recs(), station="x", created=5, block_size=1)
    b = tmp_path / "b.slog"
    assert migrate(a, b, block_size=2) == 3
    assert b.read_bytes() == spec_v2(golden_recs(), "x", 5, 2)


# --- record API ------------------------------------------------------------------------------

def test_record_quality_field():
    r = Record(1, 2, 3)
    assert r.quality == 100
    assert Record(1, 2, 3, "x", True, 0).quality == 0
    assert r.replace(quality=5).quality == 5
    for bad in (101, -1):
        with pytest.raises(ValueError):
            Record(1, 2, 3, quality=bad)
    with pytest.raises(TypeError):
        Record(1, 2, 3, quality=True)
    with pytest.raises(TypeError):
        Record(1, 2, 3, quality=50.0)
    Record(1, -(2 ** 63), 1)
    Record(1, 2 ** 63 - 1, 1)


def test_v2_preserves_unicode_nul_and_long_labels(tmp_path):
    recs = [Record(1, 1, 1, "日本語ラベル" * 10), Record(2, 2, 2.5, "a\x00b", quality=7),
            Record(3, -10 ** 18, -1.0, "x" * 65535)]
    p = tmp_path / "u.slog"
    write_log(p, recs, station="ステーション\x00", created=-3)
    rd = LogReader(p)
    assert rd.records == recs and rd.station == "ステーション\x00" and rd.created == -3


def test_v2_label_too_long(tmp_path):
    p = tmp_path / "l.slog"
    with pytest.raises(ValueError):
        write_log(p, [Record(1, 1, 1, "é" * 40000)])
    with pytest.raises(ValueError):
        write_log(p, [], station="x" * 65536)
    assert not p.exists()


def test_write_version_and_block_size_validation(tmp_path):
    p = tmp_path / "v.slog"
    with pytest.raises(UnsupportedVersionError):
        write_log(p, golden_recs(), version=3)
    with pytest.raises(ValueError):
        write_log(p, golden_recs(), block_size=0)
    write_log(p, [Record(1, 9 * US, 2.0)], created=US, version=1, block_size=0)
    assert LogReader(p).version == 1


# --- NotRepresentableError ---------------------------------------------------------------------

V1_BAD = [
    (lambda: Record(1, 1_500_000, 1), "timestamp"),
    (lambda: Record(1, -US, 1), "timestamp"),
    (lambda: Record(1, 2 ** 32 * US, 1), "timestamp"),
    (lambda: Record(1, US, 1, "日本"), "label"),
    (lambda: Record(1, US, 1, "x" * 25), "label"),
    (lambda: Record(1, US, 1, "a\x00"), "label"),
    (lambda: Record(1, US, 1, quality=99), "quality"),
]


def test_v1_not_representable_record(tmp_path):
    good = Record(2, 5 * US, 1.0, "ok")
    for mk, field in V1_BAD:
        with pytest.raises(NotRepresentableError) as ei:
            write_log(tmp_path / "x.slog", [good, good, mk()], created=0, version=1)
        assert ei.value.field == field
        assert ei.value.record_index == 2


def test_v1_not_representable_order(tmp_path):
    assert issubclass(NotRepresentableError, SenslogError)
    assert issubclass(NotRepresentableError, ValueError)
    bad = Record(1, 1_000_001, 1, "日", quality=1)
    p = tmp_path / "o.slog"
    with pytest.raises(NotRepresentableError) as ei:
        write_log(p, [bad], station="ü" * 17, created=1, version=1)
    assert (ei.value.field, ei.value.record_index) == ("station", None)
    with pytest.raises(NotRepresentableError) as ei:
        write_log(p, [bad], station="ok", created=1, version=1)
    assert (ei.value.field, ei.value.record_index) == ("created", None)
    with pytest.raises(NotRepresentableError) as ei:
        write_log(p, [Record(1, US, 1, "日", quality=1)], created=0, version=1)
    assert ei.value.field == "label"
    with pytest.raises(NotRepresentableError) as ei:
        write_log(p, [Record(1, US, 1, quality=1), bad], created=0, version=1)
    assert (ei.value.field, ei.value.record_index) == ("quality", 0)


def test_failed_write_leaves_no_trace(tmp_path):
    p = tmp_path / "keep.slog"
    write_log(p, golden_recs(), station="s", created=1)
    before = p.read_bytes()
    recs = [Record(1, US, 1)] * 300 + [Record(1, US, 1, "日")]
    with pytest.raises(NotRepresentableError):
        write_log(p, recs, created=0, version=1)
    assert p.read_bytes() == before
    q = tmp_path / "new.slog"
    with pytest.raises(NotRepresentableError):
        write_log(q, recs, created=0, version=1)
    assert sorted(x.name for x in tmp_path.iterdir()) == ["keep.slog"]


# --- corruption reporting ----------------------------------------------------------------------

LABEL = "abcd"
REC_LEN = 21 + 2 + len(LABEL)


def corrupt_base(tmp_path):
    """10 records, block_size 4 -> blocks of 4, 4, 2. Station 'st'."""
    recs = [Record(i, i * US, i, LABEL) for i in range(10)]
    data = bytearray(spec_v2(recs, "st", 0, 4))
    hdr = 28 + 2 + 2 + 4
    blocks = []
    pos = hdr
    for n in (4, 4, 2):
        blocks.append(pos)
        pos += 8 + n * REC_LEN + 4
    return data, blocks, pos  # pos == index_offset


def fix_block_crc(data, start, n):
    end = start + 8 + n * REC_LEN
    data[end:end + 4] = struct.pack("<I", crc(bytes(data[start:end])))


def fix_index_crc(data, index_offset):
    idx = bytes(data[index_offset:len(data) - 20])
    data[len(data) - 8:len(data) - 4] = struct.pack("<I", crc(idx))


def load(tmp_path, data):
    p = tmp_path / "c.slog"
    p.write_bytes(bytes(data))
    with pytest.raises(CorruptFileError) as ei:
        LogReader(p)
    return ei.value


def test_corrupt_block_crc(tmp_path):
    data, blocks, _ = corrupt_base(tmp_path)
    p = tmp_path / "ok.slog"
    p.write_bytes(bytes(data))
    assert len(LogReader(p)) == 10
    data[blocks[1] + 8 + REC_LEN + 15] ^= 0x40  # value byte of record 5
    e = load(tmp_path, data)
    assert e.block_index == 1 and e.record_index is None
    assert str(e).startswith("block 1: ")


def test_corrupt_record_kind(tmp_path):
    data, blocks, _ = corrupt_base(tmp_path)
    data[blocks[1] + 8 + 2 * REC_LEN + 2] = 9  # kind of record 6
    fix_block_crc(data, blocks[1], 4)
    e = load(tmp_path, data)
    assert (e.block_index, e.record_index) == (1, 6)
    assert str(e).startswith("block 1: ") and "record 6" in str(e)


def test_corrupt_record_flags_and_quality(tmp_path):
    data, blocks, _ = corrupt_base(tmp_path)
    data[blocks[2] + 8 + REC_LEN + 4] = 101  # quality of record 9
    data[blocks[2] + 8 + 3] = 0x80  # flags of record 8
    fix_block_crc(data, blocks[2], 2)
    e = load(tmp_path, data)
    assert (e.block_index, e.record_index) == (2, 8)
    data[blocks[2] + 8 + 3] = 0x01
    fix_block_crc(data, blocks[2], 2)
    e = load(tmp_path, data)
    assert (e.block_index, e.record_index) == (2, 9) and "record 9" in str(e)


def test_corrupt_label_utf8(tmp_path):
    data, blocks, _ = corrupt_base(tmp_path)
    data[blocks[0] + 8 + 3 * REC_LEN + 23] = 0xFF  # first label byte of record 3
    fix_block_crc(data, blocks[0], 4)
    e = load(tmp_path, data)
    assert (e.block_index, e.record_index) == (0, 3)


def test_corrupt_label_overrun(tmp_path):
    data, blocks, _ = corrupt_base(tmp_path)
    data[blocks[2] + 8 + REC_LEN + 21] = 200  # label length of record 9
    fix_block_crc(data, blocks[2], 2)
    e = load(tmp_path, data)
    assert (e.block_index, e.record_index) == (2, 9)


def test_corrupt_index_entry(tmp_path):
    data, blocks, idx = corrupt_base(tmp_path)
    data[idx + 32 + 16] ^= 0x01  # min_timestamp of block 1
    fix_index_crc(data, idx)
    e = load(tmp_path, data)
    assert e.block_index == 1 and e.record_index is None and "index" in str(e)


def test_corrupt_index_crc_and_trailer(tmp_path):
    data, blocks, idx = corrupt_base(tmp_path)
    d1 = bytearray(data)
    d1[idx + 70] ^= 0x01
    e = load(tmp_path, d1)
    assert e.block_index is None and e.record_index is None and "index" in str(e)
    d2 = bytearray(data)
    d2[-1:] = b"X"
    e = load(tmp_path, d2)
    assert e.block_index is None and "index" in str(e)
    d3 = bytearray(data)
    d3[-12:-8] = struct.pack("<I", 4)
    e = load(tmp_path, d3)
    assert e.block_index is None and "index" in str(e)


def test_corrupt_header(tmp_path):
    data, blocks, idx = corrupt_base(tmp_path)
    d1 = bytearray(data)
    d1[31] ^= 0x01  # station byte
    e = load(tmp_path, d1)
    assert e.block_index is None and e.record_index is None and "header" in str(e)
    d2 = bytearray(data)
    d2[16:20] = struct.pack("<I", 11)
    d2[32:36] = struct.pack("<I", crc(bytes(d2[:32])))
    e = load(tmp_path, d2)
    assert e.block_index is None and e.record_index is None
    e = load(tmp_path, data[:20])
    assert e.block_index is None


def test_corrupt_truncated_and_bad_version(tmp_path):
    data, blocks, idx = corrupt_base(tmp_path)
    load(tmp_path, data[:-3])
    load(tmp_path, data[:idx] + data[idx + 32:])
    d = bytearray(data)
    d[4] = 3
    p = tmp_path / "v3.slog"
    p.write_bytes(bytes(d))
    with pytest.raises(UnsupportedVersionError):
        LogReader(p)


def test_v1_corruption_unchanged(tmp_path):
    data = bytearray(V1.read_bytes())
    data[32 + 40 * 5 + 2] = 7
    data[-4:] = struct.pack("<I", crc(bytes(data[:-4])))
    e = load(tmp_path, data)
    assert e.record_index == 5 and e.block_index is None
    data = bytearray(V1.read_bytes())
    data[500] ^= 1
    e = load(tmp_path, data)
    assert e.block_index is None


# --- time, csv, stats, ops ---------------------------------------------------------------------

def test_timefmt_microseconds():
    assert format_ts(0) == "1970-01-01T00:00:00Z"
    assert format_ts(1) == "1970-01-01T00:00:00.000001Z"
    assert format_ts(-1) == "1969-12-31T23:59:59.999999Z"
    assert format_ts(1_700_000_000_999_999) == "2023-11-14T22:13:20.999999Z"
    assert format_ts(4_102_444_800_000_000) == "2100-01-01T00:00:00Z"
    assert parse_ts("2023-11-14T22:13:20.999999Z") == 1_700_000_000_999_999
    assert parse_ts("1970-01-01T00:00:01.5Z") == 1_500_000
    assert parse_ts("1970-01-01T00:01:00Z") == 60 * US
    assert parse_ts("12") == 12 * US
    for us in (1_234_567_890_123_456, 7, -999_999, 253_402_300_799_999_999):
        assert parse_ts(format_ts(us)) == us


def test_csv_quality():
    recs = [Record(1, 1_500_000, 1.25, "q", True, 37), Record(2, 3 * US, -4)]
    text = csvio.records_to_csv_text(recs)
    lines = text.splitlines()
    assert lines[0] == "sensor,timestamp,value,label,calibrated,quality"
    assert lines[1] == "1,1970-01-01T00:00:01.500000Z,1.25,q,1,37"
    assert lines[2] == "2,1970-01-01T00:00:03Z,-4,,0,100"
    assert csvio.records_from_csv_text(text) == recs
    assert csvio.records_from_csv_text("1,5,2\n3,6,1.0,x,1\n") == [Record(1, 5 * US, 2),
                                                                  Record(3, 6 * US, 1.0, "x", True)]
    with pytest.raises(csvio.CsvImportError):
        csvio.records_from_csv_text("1,5,2,x,0,100,extra\n")


def test_stats_and_ops():
    recs = [Record(1, 0, 1.0, quality=50), Record(1, 2_500_000, 3.0, quality=90),
            Record(2, US, 5, quality=90), Record(2, US, 5, quality=80)]
    s = stats.summarize(recs)
    assert s[1].first_ts == 0 and s[1].last_ts == 2_500_000
    assert s[1].span == pytest.approx(2.5) and s[1].rate == pytest.approx(0.4)
    assert s[2].rate is None
    assert list(ops.filter_records(recs, min_quality=85)) == [recs[1], recs[2]]
    assert list(ops.filter_records(recs, sensors=[2], min_quality=85)) == [recs[2]]
    assert ops.dedupe(recs + [recs[3]]) == recs


# --- CLI -----------------------------------------------------------------------------------------

def test_cli_migrate_and_info(tmp_path, capsys):
    out = tmp_path / "m.slog"
    assert main(["migrate", str(V1), str(out), "--block-size", "100"]) == 0
    assert f"migrated 600 records to {out}" in capsys.readouterr().out
    station, created, recs = expected_fixture()
    assert out.read_bytes() == spec_v2(recs, station, created, 100)
    assert main(["info", str(out)]) == 0
    o = capsys.readouterr().out.splitlines()
    assert "version: 2" in o and "blocks: 6" in o
    assert o.index("blocks: 6") == o.index("records: 600") + 1
    assert main(["info", str(V1)]) == 0
    o = capsys.readouterr().out
    assert "version: 1" in o and "blocks:" not in o
    assert main(["verify", str(out), str(V1)]) == 0


def test_cli_import_filter_merge_versions(tmp_path, capsys):
    csvp = tmp_path / "in.csv"
    csvp.write_text("sensor,timestamp,value,label,calibrated,quality\n"
                    "1,1970-01-01T00:00:01.250000Z,1.5,a,1,40\n"
                    "2,1970-01-01T00:00:02Z,7,b,0,100\n", encoding="utf-8")
    a = tmp_path / "a.slog"
    assert main(["import", str(csvp), str(a), "--created", "0"]) == 0
    assert LogReader(a).version == 2
    assert read_records(a)[0] == Record(1, 1_250_000, 1.5, "a", True, 40)
    bad = tmp_path / "bad.slog"
    capsys.readouterr()
    assert main(["import", str(csvp), str(bad), "--created", "0", "--format-version", "1"]) == 2
    assert not bad.exists()
    f = tmp_path / "f.slog"
    assert main(["filter", str(a), str(f), "--min-quality", "90"]) == 0
    assert read_records(f) == [Record(2, 2 * US, 7, "b", False, 100)]
    f1 = tmp_path / "f1.slog"
    assert main(["filter", str(a), str(f1), "--min-quality", "90", "--format-version", "1"]) == 0
    assert LogReader(f1).version == 1 and LogReader(f1).records == read_records(f)
    m = tmp_path / "m.slog"
    assert main(["merge", str(m), str(V1), str(f1), "--format-version", "1"]) == 0
    assert LogReader(m).version == 1 and len(LogReader(m)) == 601
    m2 = tmp_path / "m2.slog"
    assert main(["merge", str(m2), str(a), str(f)]) == 0
    assert LogReader(m2).version == 2 and len(LogReader(m2)) == 3


def test_cli_verify_v2_corrupt(tmp_path, capsys):
    data, blocks, _ = corrupt_base(tmp_path)
    data[blocks[2] + 9] ^= 1
    p = tmp_path / "c.slog"
    p.write_bytes(bytes(data))
    assert main(["verify", str(p)]) == 1
    assert "CORRUPT" in capsys.readouterr().out


# --- regressions: existing behaviour that must keep working ------------------------------------

def test_regression_record_validation():
    with pytest.raises(ValueError):
        Record(70000, 1, 1)
    with pytest.raises(TypeError):
        Record(1, 1, True)
    with pytest.raises(ValueError):
        Record(1, 1, 2 ** 63)
    with pytest.raises(TypeError):
        Record(1, 1.0, 1)


def test_regression_v1_reader_basics(tmp_path, capsys):
    rd = LogReader(V1)
    assert len(rd) == 600 and rd.sensors() == [1, 2, 3, 7, 42, 300, 65535]
    assert main(["verify", str(V1), str(V1_EMPTY)]) == 0
    assert capsys.readouterr().out.count(": OK (version 1,") == 2
    bad = tmp_path / "magic.slog"
    bad.write_bytes(b"XLOG" + V1.read_bytes()[4:])
    with pytest.raises(CorruptFileError):
        LogReader(bad)
    short = tmp_path / "short.slog"
    short.write_bytes(V1.read_bytes()[:-1])
    with pytest.raises(CorruptFileError):
        LogReader(short)


def test_regression_ops_merge_dedupe():
    a = [Record(1, 10, 1), Record(2, 30, 2)]
    b = [Record(1, 20, 3), Record(1, 10, 1)]
    m = ops.merge(a, b)
    assert ops.is_sorted(m) and len(m) == 4
    assert ops.dedupe(m) == [Record(1, 10, 1), Record(1, 20, 3), Record(2, 30, 2)]
    assert list(ops.filter_records(m, start=15, end=30)) == [Record(1, 20, 3)]
