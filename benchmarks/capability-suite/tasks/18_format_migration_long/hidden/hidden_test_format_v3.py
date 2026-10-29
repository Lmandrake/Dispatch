import io
import json
import math
import struct
import zlib
from pathlib import Path

import pytest

import tsarc
from tsarc import (ArchiveReader, ArchiveWriter, ChecksumError, Column, FormatError,
                   NotRepresentableError, Schema, SchemaError, Table, UnsupportedVersionError,
                   append_rows, convert, read_table, set_metadata, write_archive)
from tsarc import csvio, jsonio
from tsarc.cli import main
from tsarc.ops import resample
from tsarc.stats import column_stats, render_stats
from tsarc.verify import verify_file

import hidden_spec3 as S

HERE = Path(__file__).parent
T0 = 1_772_323_200_000_000
SEC = 1_000_000
migrate = getattr(tsarc, "migrate", None)
add_column = getattr(tsarc, "add_column", None)


# --- helpers -----------------------------------------------------------------------------------

def fx(name):
    return HERE / name


def obs_expected():
    d = json.loads(fx("fixture_obs.json").read_text(encoding="utf-8"))
    cols = [[float.fromhex(v["f"]) if isinstance(v, dict) else v for v in col] for col in d["columns"]]
    return Schema.parse(d["schema"]), cols, d["metadata"]


OBS_COLS = [("ts", "ts", False), ("temp", "float", False), ("hum", "float", True),
            ("cnt", "int", True), ("tag", "str", True), ("flag", "bool", True), ("note", "str", False)]


def spec_cols(schema):
    return [(c.name, c.type, c.to_text().endswith("?")) for c in schema]


def cols_of(table):
    return [table.column(n) for n in table.schema.names]


def spec_bytes(table, meta=None, chunk_rows=1024):
    return S.encode_v3(spec_cols(table.schema), cols_of(table), meta or {}, chunk_rows)


def put(tmp_path, data, name="t.tsa"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def bits(v):
    return struct.pack("<d", v)


class Counter:
    def __init__(self, monkeypatch):
        self.calls = 0
        real = zlib.decompress

        def counting(*a, **k):
            self.calls += 1
            return real(*a, **k)
        monkeypatch.setattr(zlib, "decompress", counting)


def run(capsys, *argv):
    try:
        rc = main([str(a) for a in argv])
    except SystemExit as exc:
        rc = exc.code
    out, err = capsys.readouterr()
    return rc, out, err


def tbl(text, *cols):
    schema = Schema.parse(text)
    if not cols:
        return Table(schema)
    return Table(schema, [list(c) for c in cols])


# --- golden bytes: encodings ------------------------------------------------------------------

GOLDEN_SPECS = {
    "delta2_example": lambda: tbl("ts:ts", [1000, 1010, 1020, 1031]),
    "xor_example": lambda: tbl("ts:ts,x:float", [0, 1, 2], [1.0, 1.0, 1.5]),
    "big_ints_plain": lambda: tbl("ts:ts,n:int", [0, 1, 2, 3], [2 ** 62, -2 ** 62, 2 ** 63 - 1, -2 ** 63]),
    "small_ints_varint": lambda: tbl("ts:ts,n:int", list(range(10)), [0, -1, 1, -64, 63, 64, 300, -300, 7, 0]),
    "int_tie_plain": lambda: tbl("ts:ts,n:int", [5], [2 ** 50]),
    "ts_tie_plain": lambda: tbl("ts:ts", [2 ** 50]),
    "ts_wrapping": lambda: tbl("ts:ts", [-2 ** 63, 2 ** 63 - 1, -2 ** 63, 0, 2 ** 63 - 1]),
    "ts_unsorted": lambda: tbl("ts:ts", [50, 10, 40, 40, -3, 1000000]),
    "str_dict": lambda: tbl("ts:ts,s:str", list(range(8)), ["roof", "yard", "roof", "roof", "Ω", "", "yard", "roof"]),
    "str_plain": lambda: tbl("ts:ts,s:str", [1, 2, 3], ["alpha", "beta", "日本語"]),
    "str_single": lambda: tbl("ts:ts,s:str", [1], ["a"]),
    "bools": lambda: tbl("ts:ts,b:bool", list(range(11)), [True, False, True, True, False, False, False, True, True, False, True]),
    "floats_special": lambda: tbl("ts:ts,x:float", list(range(7)), [math.inf, -math.inf, math.nan, 5e-324, -0.0, 0.0, 1e300]),
    "float_negzero_first": lambda: tbl("ts:ts,x:float", [1, 2, 3, 4], [math.nan, -0.0, 0.0, math.nan]),
    "float_zero_first": lambda: tbl("ts:ts,x:float", [1, 2, 3], [0.0, -0.0, math.nan]),
    "float_all_nan": lambda: tbl("ts:ts,x:float", [1, 2], [math.nan, math.nan]),
    "nullable_mixed": lambda: tbl("ts:ts,h:float?,n:int?,s:str?,b:bool?", list(range(9)),
                          [None, 1.5, 1.5, None, 2.0, None, None, 3.0, None],
                          [1, None, 2, None, None, -5, 6, 7, None],
                          ["x", "x", None, "y", None, None, "x", "x", "z"],
                          [None, True, False, None, True, True, None, False, None]),
    "nullable_all_null": lambda: tbl("ts:ts,h:float?,s:str?", [1, 2, 3], [None] * 3, [None] * 3),
    "nullable_no_null": lambda: tbl("ts:ts,h:float?", [1, 2, 3], [1.0, 2.0, 4.0]),
    "nullable_nan_only": lambda: tbl("ts:ts,h:float?", [1, 2, 3], [None, math.nan, None]),
    "compressible": lambda: tbl("ts:ts,x:float,n:int,s:str", [T0 + i * SEC for i in range(400)],
                        [20.5 + (i % 5) for i in range(400)], [i % 3 for i in range(400)],
                        ["roof" if i % 2 else "yard" for i in range(400)]),
    "empty": lambda: tbl("ts:ts,x:float?,s:str"),
}


class _Golden:
    def __getitem__(self, name):
        return GOLDEN_SPECS[name]()


GOLDEN = _Golden()


@pytest.mark.parametrize("name", sorted(GOLDEN_SPECS))
def test_golden_v3_bytes(tmp_path, name):
    t = GOLDEN[name]
    p = tmp_path / "g.tsa"
    write_archive(p, t)
    assert p.read_bytes() == spec_bytes(t)
    rd = ArchiveReader(p)
    assert rd.version == 3
    assert rd.table == t


@pytest.mark.parametrize("name", ["nullable_mixed", "compressible", "bools", "ts_wrapping"])
@pytest.mark.parametrize("chunk_rows", [1, 2, 3, 100])
def test_golden_chunked(tmp_path, name, chunk_rows):
    t = GOLDEN[name]
    p = tmp_path / "g.tsa"
    write_archive(p, t, {"k": "v", "x.y": "ü é"}, version=3, chunk_rows=chunk_rows)
    assert p.read_bytes() == spec_bytes(t, {"k": "v", "x.y": "ü é"}, chunk_rows)
    rd = ArchiveReader(p)
    assert rd.table == t
    assert rd.chunk_rows == chunk_rows
    assert rd.chunk_count == -(-t.num_rows // chunk_rows)


def test_delta2_example_segment_bytes(tmp_path):
    p = tmp_path / "d.tsa"
    write_archive(p, GOLDEN["delta2_example"])
    hdr = S.build([("ts", "ts", False)], [[1]]).header()
    assert p.read_bytes()[len(hdr):len(hdr) + 5] == bytes.fromhex("d00f140002")
    seg = ArchiveReader(p).chunks[0].segments["ts"]
    assert (seg.encoding, seg.codec, seg.raw_len, seg.stored_len) == ("delta2", "none", 5, 5)


def test_xor_example_segment_bytes(tmp_path):
    p = tmp_path / "x.tsa"
    write_archive(p, GOLDEN["xor_example"])
    data = p.read_bytes()
    assert bytes.fromhex("063ff0801608") in data
    seg = ArchiveReader(p).chunks[0].segments["x"]
    assert (seg.encoding, seg.raw_len, seg.min, seg.max) == ("xor", 6, 1.0, 1.5)


def test_encoding_choices(tmp_path):
    expect = {"big_ints_plain": ("n", "plain"), "small_ints_varint": ("n", "varint"),
              "int_tie_plain": ("n", "plain"), "ts_tie_plain": ("ts", "plain"),
              "str_dict": ("s", "dict"), "str_plain": ("s", "plain"), "str_single": ("s", "plain"),
              "bools": ("b", "bitpack"), "nullable_all_null": ("h", "null")}
    for name, (col, enc) in expect.items():
        p = tmp_path / f"{name}.tsa"
        write_archive(p, GOLDEN[name])
        assert ArchiveReader(p).chunks[0].segments[col].encoding == enc, name


def test_stats_first_of_equal_values(tmp_path):
    p = tmp_path / "z.tsa"
    write_archive(p, GOLDEN["float_negzero_first"])
    seg = ArchiveReader(p).chunks[0].segments["x"]
    assert bits(seg.min) == bits(-0.0) and bits(seg.max) == bits(-0.0)
    write_archive(p, GOLDEN["float_zero_first"])
    seg = ArchiveReader(p).chunks[0].segments["x"]
    assert bits(seg.min) == bits(0.0) and bits(seg.max) == bits(0.0)
    write_archive(p, GOLDEN["float_all_nan"])
    seg = ArchiveReader(p).chunks[0].segments["x"]
    assert seg.min is None and seg.max is None


# --- fixtures and migration ---------------------------------------------------------------------

def test_obs_fixture_reads():
    schema, cols, meta = obs_expected()
    rd = ArchiveReader(fx("fixture_obs_v3.tsa"))
    assert rd.version == 3
    assert rd.schema == schema
    assert rd.schema.to_text() == "ts:ts,temp:float,hum:float?,cnt:int?,tag:str?,flag:bool?,note:str"
    assert rd.metadata == meta and list(rd.metadata) == ["kind", "empty"]
    assert rd.num_rows == 260
    assert rd.chunk_rows == 50 and rd.chunk_count == 6
    assert rd.table == Table(schema, cols)


def test_obs_fixture_rewrite_identical(tmp_path):
    rd = ArchiveReader(fx("fixture_obs_v3.tsa"))
    out = tmp_path / "o.tsa"
    write_archive(out, rd.table, rd.metadata, chunk_rows=50)
    assert out.read_bytes() == fx("fixture_obs_v3.tsa").read_bytes()


@pytest.mark.parametrize("cr,name", [(64, "fixture_weather_v3_c64.tsa"), (None, "fixture_weather_v3.tsa")])
def test_migrate_v2_fixture(tmp_path, cr, name):
    out = tmp_path / "m.tsa"
    n = migrate(fx("fixture_weather_v2.tsa"), out) if cr is None else \
        migrate(str(fx("fixture_weather_v2.tsa")), str(out), chunk_rows=cr)
    assert n == 300
    assert out.read_bytes() == fx(name).read_bytes()


def test_migrate_v1_fixture(tmp_path):
    out = tmp_path / "m.tsa"
    assert migrate(fx("fixture_weather_v1.tsa"), out, chunk_rows=100) == 300
    t = ArchiveReader(fx("fixture_weather_v1.tsa")).table
    assert out.read_bytes() == spec_bytes(t, {}, 100)


def test_v3_fixture_converts_back_to_v2_bytes(tmp_path):
    out = tmp_path / "back.tsa"
    assert convert(fx("fixture_weather_v3_c64.tsa"), out, 2) == 300
    assert out.read_bytes() == fx("fixture_weather_v2.tsa").read_bytes()


def test_migrate_empty(tmp_path):
    out = tmp_path / "e.tsa"
    assert migrate(fx("fixture_empty_v2.tsa"), out) == 0
    rd = ArchiveReader(out)
    assert rd.chunk_count == 0 and rd.chunks == [] and rd.time_range() is None
    assert out.read_bytes() == S.encode_v3([("ts", "ts", False), ("v", "float", False)], [[], []], {}, 1024)


@pytest.mark.parametrize("version,name", [(1, "fixture_weather_v1.tsa"), (2, "fixture_weather_v2.tsa"),
                                          (2, "fixture_empty_v2.tsa")])
def test_old_versions_still_byte_identical(tmp_path, version, name):
    rd = ArchiveReader(fx(name))
    out = tmp_path / "c.tsa"
    write_archive(out, rd.table, rd.metadata, version=version)
    assert out.read_bytes() == fx(name).read_bytes()


def test_v2_writer_matches_spec(tmp_path):
    t = GOLDEN["bools"]
    p = tmp_path / "b.tsa"
    write_archive(p, t, {"a": "1"}, version=2)
    assert p.read_bytes() == S.encode_v2(spec_cols(t.schema), cols_of(t), {"a": "1"})
    t1 = tbl("ts:ts,s:str,x:float,n:int", [3, 1], ["Zürich", ""], [1.5, math.nan], [-1, 2 ** 63 - 1])
    write_archive(p, t1, version=1)
    assert p.read_bytes() == S.encode_v1(spec_cols(t1.schema), cols_of(t1))


# --- reader API ---------------------------------------------------------------------------------

def test_chunk_info_api():
    rd = ArchiveReader(fx("fixture_obs_v3.tsa"))
    assert isinstance(rd.chunks[0], tsarc.ChunkInfo)
    assert isinstance(rd.chunks[0].segments["ts"], tsarc.SegmentInfo)
    schema, cols, meta = obs_expected()
    arch = S.build(OBS_COLS, cols, meta, 50)
    hlen = len(arch.header())
    assert [c.index for c in rd.chunks] == list(range(6))
    assert [c.rows for c in rd.chunks] == [50] * 5 + [10]
    assert [c.first_row for c in rd.chunks] == [0, 50, 100, 150, 200, 250]
    assert rd.chunks[0].offset == hlen
    off = hlen
    for ch, sch in zip(rd.chunks, arch.chunks):
        assert ch.offset == off
        assert ch.length == len(sch.body())
        off += ch.length + 4
        assert list(ch.segments) == schema.names
        for (name, ty, _), seg, sseg in zip(OBS_COLS, ch.segments.values(), sch.segments):
            assert seg.null_count == sseg.nulls
            assert seg.stored_len == len(sseg.stored) and seg.raw_len == sseg.raw_len
            assert seg.codec == ("zlib" if sseg.codec else "none")
            assert seg.encoding == ["null", "plain", "varint", "delta2", "xor", "dict", "bitpack"][sseg.enc]
            if sseg.stats is None:
                assert seg.min is None and seg.max is None
            else:
                fmt = "<d" if ty == "float" else "<q"
                assert struct.pack(fmt, seg.min) == sseg.stats[0]
                assert struct.pack(fmt, seg.max) == sseg.stats[1]
    hum = rd.chunks[1].segments["hum"]
    assert (hum.encoding, hum.codec, hum.null_count, hum.stored_len, hum.raw_len) == ("null", "none", 50, 0, 0)
    assert rd.chunks[4].segments["tag"].encoding == "null"


def test_old_versions_have_no_chunks():
    for name in ("fixture_weather_v1.tsa", "fixture_weather_v2.tsa"):
        rd = ArchiveReader(fx(name))
        assert rd.chunks is None and rd.chunk_rows is None and rd.chunk_count is None


def test_open_reads_no_chunk_data(monkeypatch):
    c = Counter(monkeypatch)
    rd = ArchiveReader(fx("fixture_obs_v3.tsa"))
    assert rd.num_rows == 260 and rd.schema.names[0] == "ts" and rd.metadata["kind"] == "obs"
    schema, cols, _ = obs_expected()
    assert rd.time_range() == (min(cols[0]), max(cols[0]))
    assert c.calls == 0
    rd.table
    assert c.calls > 0


def skip_table(n=1000, shuffle=False):
    ts = [T0 + i * 1000 for i in range(n)]
    if shuffle:
        ts = [ts[(i * 7919) % n] for i in range(n)]
    temp = [round((i % 70) * 0.25, 2) for i in range(n)]
    cnt = [i % 9 for i in range(n)]
    site = ["roof" if i % 3 else "yard" for i in range(n)]
    return tbl("ts:ts,temp:float,cnt:int,site:str", ts, temp, cnt, site)


def zlib_segments(table, chunk_rows, chunk_ids, names):
    arch = S.build(spec_cols(table.schema), cols_of(table), {}, chunk_rows)
    idx = [table.schema.names.index(n) for n in names]
    return sum(1 for k in chunk_ids for j in idx if arch.chunks[k].segments[j].codec == 1)


def expected_query(table, start, end, columns=None, pred=None):
    names = table.schema.names
    keep = [i for i, r in enumerate(table.rows())
            if (start is None or r[0] >= start) and (end is None or r[0] < end)
            and (pred is None or pred(dict(zip(names, r))))]
    out = table.take(keep)
    return out if columns is None else out.select(columns)


@pytest.mark.parametrize("start_row,end_row,chunks", [
    (350, 450, [3, 4]), (300, 400, [3]), (299, 301, [2, 3]), (0, 1, [0]), (999, None, [9]),
    (None, 100, [0]), (None, None, list(range(10))), (2000, 3000, []),
])
def test_query_skips_chunks(tmp_path, monkeypatch, start_row, end_row, chunks):
    t = skip_table()
    p = tmp_path / "q.tsa"
    write_archive(p, t, chunk_rows=100)
    assert p.read_bytes() == spec_bytes(t, {}, 100)
    start = None if start_row is None else T0 + start_row * 1000
    end = None if end_row is None else T0 + end_row * 1000
    rd = ArchiveReader(p)
    c = Counter(monkeypatch)
    q = rd.query(start, end)
    assert q == expected_query(t, start, end)
    assert c.calls == zlib_segments(t, 100, chunks, t.schema.names)


def test_query_decodes_only_needed_columns(tmp_path, monkeypatch):
    t = skip_table()
    p = tmp_path / "q.tsa"
    write_archive(p, t, chunk_rows=100)
    start, end = T0 + 150_000, T0 + 420_000
    rd = ArchiveReader(p)
    c = Counter(monkeypatch)
    q = rd.query(start, end, columns=["temp"])
    assert q == expected_query(t, start, end, ["temp"])
    assert c.calls == zlib_segments(t, 100, [1, 2, 3, 4], ["ts", "temp"])
    rd = ArchiveReader(p)
    c.calls = 0
    q = rd.query(start, end, columns=["temp"], where="cnt > 4")
    assert q == expected_query(t, start, end, ["temp"], lambda r: r["cnt"] > 4)
    assert c.calls == zlib_segments(t, 100, [1, 2, 3, 4], ["ts", "temp", "cnt"])


def test_query_callable_where_uses_all_columns(tmp_path, monkeypatch):
    t = skip_table()
    p = tmp_path / "q.tsa"
    write_archive(p, t, chunk_rows=100)
    rd = ArchiveReader(p)
    c = Counter(monkeypatch)
    q = rd.query(T0, T0 + 100_000, columns=["cnt"], where=lambda r: r["site"] == "yard")
    assert q == expected_query(t, T0, T0 + 100_000, ["cnt"], lambda r: r["site"] == "yard")
    assert c.calls == zlib_segments(t, 100, [0], t.schema.names)


def test_query_unsorted_time(tmp_path, monkeypatch):
    t = skip_table(shuffle=True)
    p = tmp_path / "q.tsa"
    write_archive(p, t, chunk_rows=100)
    start, end = T0 + 10_000, T0 + 20_000
    rd = ArchiveReader(p)
    q = rd.query(start, end)
    assert q == expected_query(t, start, end)
    assert q.num_rows == 10


def test_column_decodes_only_that_column(tmp_path, monkeypatch):
    t = skip_table()
    p = tmp_path / "q.tsa"
    write_archive(p, t, chunk_rows=100)
    rd = ArchiveReader(p)
    c = Counter(monkeypatch)
    assert rd.column("site") == t.column("site")
    assert c.calls == zlib_segments(t, 100, range(10), ["site"])


def test_skipped_corrupt_chunk_is_not_read(tmp_path):
    t = skip_table(300)
    arch = S.build(spec_cols(t.schema), cols_of(t), {}, 100)
    arch.chunks[2].crc = 12345
    p = put(tmp_path, arch.to_bytes())
    rd = ArchiveReader(p)
    assert rd.query(T0, T0 + 150_000) == expected_query(t, T0, T0 + 150_000)
    with pytest.raises(ChecksumError) as ei:
        rd.query(T0 + 250_000, None)
    assert str(ei.value) == "chunk 2: checksum mismatch"
    assert (ei.value.chunk, ei.value.column) == (2, None)


# --- error reporting ---------------------------------------------------------------------------

def base_archive(meta=None, chunk_rows=4):
    cols = [("ts", "ts", False), ("temp", "float", False), ("hum", "float", True), ("site", "str", False)]
    vals = [[T0 + i for i in range(10)], [float(i) / 2 for i in range(10)],
            [None if i % 3 == 0 else float(i) for i in range(10)], ["ab"[i % 2] * 30 for i in range(10)]]
    return S.build(cols, vals, meta or {"m": "x"}, chunk_rows)


def open_err(tmp_path, data):
    p = put(tmp_path, data)
    with pytest.raises(FormatError) as ei:
        ArchiveReader(p)
    return ei.value


def mut_header_flags(a):
    a.flags = 1


def mut_coltype(a):
    a.cols[1] = (9, 0, b"temp")


def mut_colflags(a):
    a.cols[2] = (3, 3, b"hum")


def mut_chunk_rows0(a):
    a.chunk_rows = 0


def mut_dup(a):
    a.cols[3] = (4, 0, b"temp")


def mut_nullable_time(a):
    a.cols[0] = (1, 1, b"ts")


def mut_first_not_ts(a):
    a.cols[0] = (2, 0, b"ts")


def mut_meta_utf8(a):
    a.meta = [("m", b"\xff\xfe")]


def mut_footer_crc(a):
    a.footer_crc = 1


def mut_end_magic(a):
    a.end_magic = b"TSR2"


def mut_footer_pos(a):
    a.footer_offset = 5


def mut_footer_extra(a):
    a.footer_extra = b"\0"


def mut_footer_trunc(a):
    a.chunk_count = 4


def mut_chunk_offset(a):
    a.chunks[1].offset = 1


def mut_chunk_gap(a):
    a.chunks[0].extra = b"\0\0"


def mut_rows_not_full(a):
    a.chunk_rows = 5


def mut_last_rows(a):
    a.chunks[2].rows = 5
    a.row_count = 11


def mut_enc_ts(a):
    a.chunks[0].segments[0].enc = 4


def mut_enc_null_nonnullable(a):
    a.chunks[1].segments[1].enc = 0


def mut_enc_unknown(a):
    a.chunks[0].segments[2].enc = 9


def mut_codec(a):
    a.chunks[2].segments[3].codec = 2


def mut_nulls_nonnullable(a):
    a.chunks[0].segments[1].nulls = 1


def mut_nulls_too_many(a):
    a.chunks[1].segments[2].nulls = 5


def mut_nulls_all_nonnull_enc(a):
    a.chunks[1].segments[2].nulls = 4


def mut_stats_flag2(a):
    s = a.chunks[0].segments[1]
    s.has_stats, s.stats = 2, None


def mut_stats_str(a):
    s = a.chunks[1].segments[3]
    s.has_stats, s.stats = 1, (b"\0" * 8, b"\0" * 8)


def mut_stats_ts_missing(a):
    s = a.chunks[0].segments[0]
    s.has_stats, s.stats = 0, None


def mut_chunk_length(a):
    a.chunks[0].length = len(a.chunks[0].body()) + 1


def mut_chunks_end(a):
    a.chunks[2].extra = b"\0"


def mut_row_count(a):
    a.row_count = 11


OPEN_ERRORS = [
    (mut_header_flags, FormatError, "header: unknown flags 0x0001"),
    (mut_coltype, FormatError, "header: column 1 has unknown type code 9"),
    (mut_colflags, FormatError, "header: column 2 has unknown flags 0x03"),
    (mut_chunk_rows0, FormatError, "header: chunk_rows must be at least 1"),
    (mut_dup, FormatError, "header: bad schema: duplicate column name 'temp'"),
    (mut_nullable_time, FormatError, "header: bad schema: the time column cannot be nullable"),
    (mut_first_not_ts, FormatError, "header: bad schema: the first column must have type ts (the time column), got ts:int"),
    (mut_meta_utf8, FormatError, "header: invalid UTF-8"),
    (mut_end_magic, FormatError, "trailer: bad end magic"),
    (mut_footer_pos, FormatError, "trailer: bad footer position"),
    (mut_footer_crc, ChecksumError, "footer: checksum mismatch"),
    (mut_footer_trunc, FormatError, "footer: truncated"),
    (mut_footer_extra, FormatError, "footer: unexpected bytes after the last chunk entry"),
    (mut_chunk_offset, FormatError, "footer: chunk 1 is not where expected"),
    (mut_chunk_gap, FormatError, "footer: chunk 1 is not where expected"),
    (mut_rows_not_full, FormatError, "footer: chunk 0 has a wrong row count"),
    (mut_last_rows, FormatError, "footer: chunk 2 has a wrong row count"),
    (mut_enc_ts, FormatError, "footer: chunk 0, column 'ts': encoding 4 not allowed for type ts"),
    (mut_enc_null_nonnullable, FormatError, "footer: chunk 1, column 'temp': encoding 0 not allowed for type float"),
    (mut_enc_unknown, FormatError, "footer: chunk 0, column 'hum': encoding 9 not allowed for type float"),
    (mut_codec, FormatError, "footer: chunk 2, column 'site': unknown codec 2"),
    (mut_nulls_nonnullable, FormatError, "footer: chunk 0, column 'temp': bad null_count 1"),
    (mut_nulls_too_many, FormatError, "footer: chunk 1, column 'hum': bad null_count 5"),
    (mut_nulls_all_nonnull_enc, FormatError, "footer: chunk 1, column 'hum': bad null_count 4"),
    (mut_stats_flag2, FormatError, "footer: chunk 0, column 'temp': bad stats flag 2"),
    (mut_stats_str, FormatError, "footer: chunk 1, column 'site': bad stats flag 1"),
    (mut_stats_ts_missing, FormatError, "footer: chunk 0, column 'ts': bad stats flag 0"),
    (mut_chunk_length, FormatError, "footer: chunk 0 length does not match its segments"),
    (mut_chunks_end, FormatError, "footer: chunks do not end at the footer"),
    (mut_row_count, FormatError, "footer: row counts do not add up to row_count"),
]


@pytest.mark.parametrize("mut,cls,msg", OPEN_ERRORS, ids=[m.__name__ for m, _, _ in OPEN_ERRORS])
def test_open_errors(tmp_path, mut, cls, msg):
    a = base_archive()
    assert ArchiveReader(put(tmp_path, a.to_bytes(), "ok.tsa")).num_rows == 10
    mut(a)
    e = open_err(tmp_path, a.to_bytes())
    assert type(e) is cls
    assert str(e) == msg
    assert e.chunk is None and e.column is None


def test_header_checksum_and_truncation(tmp_path):
    a = base_archive()
    data = a.to_bytes()
    hlen = len(a.header())
    e = open_err(tmp_path, data[:hlen - 3])
    assert str(e) == "header: truncated" and type(e) is FormatError
    e = open_err(tmp_path, data[:12])
    assert str(e) == "header: truncated"
    a.header_crc = 7
    e = open_err(tmp_path, a.to_bytes())
    assert type(e) is ChecksumError and str(e) == "header: checksum mismatch"
    e = open_err(tmp_path, data[:hlen + 19])
    assert str(e) == "trailer: truncated"


def test_header_checks_crc_before_flags(tmp_path):
    a = base_archive()
    a.flags = 2
    a.header_crc = 99
    e = open_err(tmp_path, a.to_bytes())
    assert type(e) is ChecksumError and str(e) == "header: checksum mismatch"


def test_footer_offset_before_header_end(tmp_path):
    a = base_archive()
    data = bytearray(a.to_bytes())
    size = len(data)
    flen = size - 20
    struct.pack_into("<QI", data, size - 20, 0, flen)
    e = open_err(tmp_path, bytes(data))
    assert str(e) == "trailer: bad footer position"


def test_non_ascii_column_name(tmp_path):
    a = base_archive()
    a.cols[1] = (3, 0, "tëmp".encode("latin-1"))
    e = open_err(tmp_path, a.to_bytes())
    assert str(e).startswith("header: bad schema: ")


def test_unsupported_version_still(tmp_path):
    data = bytearray(base_archive().to_bytes())
    data[4] = 4
    with pytest.raises(UnsupportedVersionError):
        ArchiveReader(put(tmp_path, bytes(data)))


def test_old_version_errors_have_no_location(tmp_path):
    data = bytearray(fx("fixture_weather_v2.tsa").read_bytes())
    data[-30] ^= 0x40
    with pytest.raises(ChecksumError) as ei:
        ArchiveReader(put(tmp_path, bytes(data)))
    assert ei.value.chunk is None and ei.value.column is None
    data = bytearray(fx("fixture_weather_v1.tsa").read_bytes())
    data[50] ^= 1
    with pytest.raises(FormatError) as ei:
        ArchiveReader(put(tmp_path, bytes(data)))
    assert ei.value.chunk is None and ei.value.column is None


def seg_archive(ty, raw, enc, nullable=False, nulls=0, stats="auto", rows=1, codec=0, stored=None,
                raw_len=None):
    cols = [("ts", "ts", False), ("v", ty, nullable)]
    a = S.build(cols, [list(range(rows)), [None] * rows if nullable else
                       {"int": [0] * rows, "float": [0.0] * rows, "str": [""] * rows,
                        "bool": [False] * rows, "ts": [0] * rows}[ty]], {}, 1024)
    if stats == "auto":
        stats = None
    a.chunks[0].segments[1] = S.raw_segment(raw, enc, nulls, stats, codec, stored, raw_len)
    return a


CHUNK_ERRORS = [
    ("decompression failed", dict(ty="int", raw=b"\0" * 8, enc=1, codec=1, stored=b"not zlib",
                                  stats=S.stats_i64(0, 0))),
    ("raw length mismatch", dict(ty="int", raw=b"\0" * 8, enc=1, raw_len=9, stats=S.stats_i64(0, 0))),
    ("raw length mismatch", dict(ty="int", raw=b"\0" * 8, enc=1, codec=1, stored=zlib.compress(b"\0" * 8),
                                 raw_len=7, stats=S.stats_i64(0, 0))),
    ("truncated data", dict(ty="int", raw=b"\0" * 7, enc=1, stats=S.stats_i64(0, 0))),
    ("truncated data", dict(ty="str", raw=b"\x05abc", enc=1)),
    ("truncated data", dict(ty="int", raw=b"\x80", enc=2, stats=S.stats_i64(0, 0))),
    ("truncated data", dict(ty="float", raw=b"\x40\x01\x02", enc=4, stats=(bits(0.0), bits(0.0)))),
    ("non-zero padding bits", dict(ty="bool", raw=b"\x09", enc=6, rows=3)),
    ("non-zero padding bits", dict(ty="int", raw=b"\x23" + S.sv(0) * 2, enc=2, nullable=True, nulls=2,
                                   rows=4, stats=S.stats_i64(0, 0))),
    ("validity bitmap does not match null_count", dict(ty="int", raw=b"\x01" + S.sv(0), enc=2,
                                                       nullable=True, nulls=1, rows=3,
                                                       stats=S.stats_i64(0, 0))),
    ("varint too long", dict(ty="int", raw=b"\x80" * 10 + b"\x01", enc=2, stats=S.stats_i64(0, 0))),
    ("varint too long", dict(ty="int", raw=b"\xff" * 9 + b"\x7f", enc=2, stats=S.stats_i64(0, 0))),
    ("bad XOR control byte 0x44", dict(ty="float", raw=b"\x44\x01", enc=4, stats=(bits(0.0), bits(0.0)))),
    ("bad XOR control byte 0x08", dict(ty="float", raw=b"\x08", enc=4, stats=(bits(0.0), bits(0.0)))),
    ("bad XOR control byte 0x90", dict(ty="float", raw=b"\x90", enc=4, stats=(bits(0.0), bits(0.0)))),
    ("dictionary index out of range", dict(ty="str", raw=b"\x01\x01a\x01", enc=5)),
    ("invalid UTF-8", dict(ty="str", raw=b"\x02\xff\xfe", enc=1)),
    ("invalid UTF-8", dict(ty="str", raw=b"\x01\x01\xc3\x00", enc=5)),
    ("unexpected bytes after the last value", dict(ty="int", raw=b"\0" * 9, enc=1, stats=S.stats_i64(0, 0))),
    ("unexpected bytes after the last value", dict(ty="bool", raw=b"\x01\x00", enc=6, rows=2)),
    ("statistics do not match the data", dict(ty="int", raw=S.sv(6), enc=2, stats=S.stats_i64(5, 6))),
    ("statistics do not match the data", dict(ty="int", raw=S.sv(6), enc=2, stats=None)),
    ("statistics do not match the data", dict(ty="float", raw=b"\x80\x80", enc=4, rows=2,
                                              stats=(bits(-0.0), bits(0.0)))),
    ("statistics do not match the data", dict(ty="float", raw=struct.pack("<d", math.nan), enc=1,
                                              stats=(bits(math.nan), bits(math.nan)))),
]


@pytest.mark.parametrize("msg,kw", CHUNK_ERRORS, ids=[f"{i}-{m}" for i, (m, _) in enumerate(CHUNK_ERRORS)])
def test_chunk_data_errors(tmp_path, msg, kw):
    a = seg_archive(**kw)
    p = put(tmp_path, a.to_bytes())
    rd = ArchiveReader(p)
    assert rd.num_rows == a.row_count
    with pytest.raises(FormatError) as ei:
        rd.table
    e = ei.value
    assert type(e) is FormatError
    assert str(e) == f"chunk 0, column 'v': {msg}"
    assert (e.chunk, e.column) == (0, "v")
    res = verify_file(p)
    assert not res.ok and res.line() == f"{p}: CORRUPT: chunk 0, column 'v': {msg}"


def test_good_hand_made_segments_decode(tmp_path):
    cases = [
        (dict(ty="float", raw=bytes.fromhex("063ff0801608"), enc=4, rows=3, stats=(bits(1.0), bits(1.5))),
         [1.0, 1.0, 1.5]),
        (dict(ty="int", raw=b"\xff" * 9 + b"\x01", enc=2, stats=S.stats_i64(-2 ** 63, -2 ** 63)), [-2 ** 63]),
        (dict(ty="str", raw=b"\x02\x01a\x00\x00\x01\x00", enc=5, rows=3), ["a", "", "a"]),
        (dict(ty="bool", raw=b"\x05", enc=6, rows=3), [True, False, True]),
        (dict(ty="int", raw=b"\x05" + S.sv(-3) + S.sv(4), enc=2, nullable=True, nulls=1, rows=3,
              stats=S.stats_i64(-3, 4)), [-3, None, 4]),
        (dict(ty="int", raw=struct.pack("<q", 2 ** 50), enc=1, stats=S.stats_i64(2 ** 50, 2 ** 50)), [2 ** 50]),
    ]
    for kw, expect in cases:
        a = seg_archive(**kw)
        p = put(tmp_path, a.to_bytes())
        assert ArchiveReader(p).table.column("v") == expect, kw
        assert verify_file(p).ok


def test_chunk_checksum_error(tmp_path):
    a = base_archive()
    a.chunks[1].crc = 0
    p = put(tmp_path, a.to_bytes())
    rd = ArchiveReader(p)
    with pytest.raises(ChecksumError) as ei:
        rd.column("temp")
    assert str(ei.value) == "chunk 1: checksum mismatch"
    assert (ei.value.chunk, ei.value.column) == (1, None)
    with pytest.raises(ChecksumError):
        read_table(p)


# --- writing ----------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [0, -3, 2.5, "64"])
@pytest.mark.parametrize("version", [None, 1, 2, 3])
def test_chunk_rows_validation(tmp_path, bad, version):
    p = tmp_path / "x.tsa"
    with pytest.raises(ValueError):
        write_archive(p, GOLDEN["str_plain"], version=version, chunk_rows=bad)
    assert not p.exists()


def test_nullable_not_representable_in_old_versions(tmp_path):
    t = tbl("ts:ts,ok:bool,hum:float?,n:int?", [1], [True], [None], [2])
    p = tmp_path / "x.tsa"
    write_archive(p, GOLDEN["str_plain"], version=2)
    before = p.read_bytes()
    for version, meta in ((1, {"a": "b"}), (2, {})):
        with pytest.raises(NotRepresentableError) as ei:
            write_archive(p, t, meta, version=version)
        assert ei.value.column == "hum" and ei.value.row is None
        assert p.read_bytes() == before
    assert sorted(x.name for x in tmp_path.iterdir()) == ["x.tsa"]


def test_unknown_write_version(tmp_path):
    with pytest.raises(UnsupportedVersionError):
        write_archive(tmp_path / "x.tsa", GOLDEN["bools"], version=4)


def test_archive_writer_chunk_rows(tmp_path):
    p = tmp_path / "w.tsa"
    t = GOLDEN["nullable_mixed"]
    with ArchiveWriter(p, t.schema, {"a": "1"}, chunk_rows=2) as w:
        for r in t.rows():
            w.write_row(r)
    assert p.read_bytes() == spec_bytes(t, {"a": "1"}, 2)


def test_append_set_metadata_convert_keep_chunk_rows(tmp_path):
    t = GOLDEN["compressible"]
    p = tmp_path / "a.tsa"
    write_archive(p, t.head(100), {"k": "v"}, chunk_rows=33)
    assert append_rows(p, t.slice(100, 400)) == 400
    assert p.read_bytes() == spec_bytes(t, {"k": "v"}, 33)
    set_metadata(p, [("z", "1")])
    assert p.read_bytes() == spec_bytes(t, {"k": "v", "z": "1"}, 33)
    q = tmp_path / "c.tsa"
    convert(p, q, 3)
    assert ArchiveReader(q).chunk_rows == 33
    convert(fx("fixture_weather_v2.tsa"), q, 3)
    assert q.read_bytes() == fx("fixture_weather_v3.tsa").read_bytes()


def test_writer_default_is_v3(tmp_path):
    p = tmp_path / "d.tsa"
    with ArchiveWriter(p, "ts:ts,v:int") as w:
        w.write_row((1, 2))
    assert ArchiveReader(p).version == 3 and ArchiveReader(p).chunk_rows == 1024


# --- schema evolution -------------------------------------------------------------------------

def test_add_column(tmp_path):
    p = tmp_path / "a.tsa"
    shutil_copy(fx("fixture_weather_v3_c64.tsa"), p)
    new = add_column(p, "hum:float?")
    assert new.to_text() == "ts:ts,temp:float,pressure:int,site:str,ok:bool,hum:float?"
    rd = ArchiveReader(p)
    assert rd.schema == new and rd.chunk_rows == 64
    assert rd.metadata == ArchiveReader(fx("fixture_weather_v2.tsa")).metadata
    old = ArchiveReader(fx("fixture_weather_v2.tsa")).table
    assert rd.column("hum") == [None] * 300
    expect = old.with_column(Column("hum", "float", True), [None] * 300)
    assert rd.table == expect
    assert p.read_bytes() == spec_bytes(expect, rd.metadata, 64)
    assert [c.segments["hum"].encoding for c in rd.chunks] == ["null"] * 5
    add_column(p, Column("tag", "str", True))
    assert ArchiveReader(p).schema.names[-1] == "tag"


def test_add_column_errors(tmp_path):
    p = tmp_path / "a.tsa"
    shutil_copy(fx("fixture_weather_v3.tsa"), p)
    with pytest.raises(SchemaError) as ei:
        add_column(p, "hum:float")
    assert str(ei.value) == "a new column must be nullable"
    with pytest.raises(SchemaError):
        add_column(p, "temp:float?")
    assert p.read_bytes() == fx("fixture_weather_v3.tsa").read_bytes()
    q = tmp_path / "b.tsa"
    shutil_copy(fx("fixture_weather_v2.tsa"), q)
    with pytest.raises(NotRepresentableError) as ei:
        add_column(q, "hum:float?")
    assert ei.value.column == "hum"
    assert q.read_bytes() == fx("fixture_weather_v2.tsa").read_bytes()


def shutil_copy(src, dst):
    Path(dst).write_bytes(Path(src).read_bytes())


# --- schema and table with nulls --------------------------------------------------------------

def test_nullable_schema_text():
    c = Column.parse("hum:float?")
    assert c.nullable is True and c.type == "float" and c.to_text() == "hum:float?"
    assert Column("a", "int").nullable is False
    assert Column("a", "int", True).to_text() == "a:int?"
    s = Schema.parse("ts:ts,hum:float?,n:int")
    assert s.to_text() == "ts:ts,hum:float?,n:int"
    assert Schema.parse(s.to_text()) == s
    assert s != Schema.parse("ts:ts,hum:float,n:int")
    assert s.describe() == ["ts   ts", "hum  float?", "n    int"]
    with pytest.raises(SchemaError) as ei:
        Schema.parse("ts:ts?,a:int")
    assert str(ei.value) == "the time column cannot be nullable"


def test_table_nulls():
    s = Schema.parse("ts:ts,hum:float?,n:int")
    t = Table.from_rows(s, [(1, None, 2), (2, 3, 4)])
    assert t.column("hum") == [None, 3.0]
    with pytest.raises(SchemaError):
        Table.from_rows(s, [(1, 2.0, None)])
    assert t == Table.from_rows(s, [(1, None, 2), (2, 3.0, 4)])
    assert t != Table.from_rows(s, [(1, 0.0, 2), (2, 3.0, 4)])
    assert Table.from_rows(s, [(1, 0.0, 2)]) != Table.from_rows(s, [(1, None, 2)])


# --- CSV, JSON, stats, expressions, resample ---------------------------------------------------

def obs_table():
    schema, cols, _ = obs_expected()
    return Table(schema, cols)


def test_csv_export_nulls():
    t = obs_table()
    text = csvio.table_to_csv_text(t)
    lines = text.splitlines()
    assert lines[0] == "ts:ts,temp:float,hum:float?,cnt:int?,tag:str?,flag:bool?,note:str"
    first = lines[1].split(",")
    assert first[2] == "" and first[3] == "" and first[5] == ""
    back = csvio.csv_to_table(text)
    cols = cols_of(t)
    cols[4] = [None if v == "" else v for v in cols[4]]
    assert back == Table(t.schema, cols)


def test_csv_import_nulls():
    t = csvio.csv_to_table('ts,v\n2026-03-01,1\n2026-03-01,""\n2026-03-01,\n', "ts:ts,v:int?")
    assert t.column("v") == [1, None, None]
    t = csvio.csv_to_table('ts:ts,s:str?,u:str\n1,,\n2,x,y\n')
    assert t.column("s") == [None, "x"] and t.column("u") == ["", "y"]
    t = csvio.csv_to_table("ts,v\n2026-03-01,1\n2026-03-01,\n")
    assert "?" not in t.schema.to_text()


def test_jsonl_null():
    buf = io.StringIO()
    jsonio.table_to_jsonl(tbl("ts:ts,h:float?,s:str?", [0], [None], [None]), buf)
    assert buf.getvalue() == '{"ts":"1970-01-01T00:00:00Z","h":null,"s":null}\n'


def test_stats_with_nulls():
    t = obs_table()
    st = {s.name: s for s in column_stats(t)}
    hum = t.column("hum")
    nn = [v for v in hum if v is not None]
    assert st["hum"].nulls == hum.count(None) and st["hum"].count == len(nn)
    real = [v for v in nn if not math.isnan(v)]
    assert st["hum"].nan == len(nn) - len(real)
    assert st["hum"].min == min(real) and st["hum"].max == max(real)
    assert st["hum"].mean == pytest.approx(math.fsum(real) / len(real))
    tag = [v for v in t.column("tag") if v is not None]
    assert st["tag"].distinct == len(set(tag)) and st["tag"].nulls == 50
    flags = [v for v in t.column("flag") if v is not None]
    assert st["flag"].true == sum(flags) and st["flag"].count == len(flags)
    assert st["ts"].nulls == 0 and st["note"].nulls == 0
    out = render_stats(t)
    rows = {line.split()[0]: line for line in out.splitlines()[2:]}
    assert rows["hum"].endswith(f"nan={st['hum'].nan} nulls={st['hum'].nulls}")
    assert rows["tag"].endswith(f"distinct={st['tag'].distinct} nulls=50")
    assert rows["cnt"].endswith(f"nulls={st['cnt'].nulls}")
    assert "nulls" not in rows["note"] and "nulls" not in rows["temp"]


def _py(expr_fn):
    t = obs_table()
    names = t.schema.names
    return [i for i, r in enumerate(t.rows()) if expr_fn(dict(zip(names, r)))]


def ok(v):
    return v is not None


EXPRS = [
    ("hum > 10", lambda r: ok(r["hum"]) and r["hum"] > 10),
    ("not (hum > 10)", lambda r: not (ok(r["hum"]) and r["hum"] > 10)),
    ("hum <= 10 or hum > 10", lambda r: ok(r["hum"]) and not math.isnan(r["hum"])),
    ("hum + 1 > 11", lambda r: ok(r["hum"]) and r["hum"] + 1 > 11),
    ("-cnt < 0", lambda r: ok(r["cnt"]) and r["cnt"] > 0),
    ("tag = 'a' or cnt = 0", lambda r: r["tag"] == "a" or r["cnt"] == 0),
    ("tag != 'a'", lambda r: ok(r["tag"]) and r["tag"] != "a"),
    ("tag in ('a', 'bb')", lambda r: r["tag"] in ("a", "bb")),
    ("tag ~ 'b'", lambda r: ok(r["tag"]) and "b" in r["tag"]),
    ("len(tag) = 2", lambda r: ok(r["tag"]) and len(r["tag"]) == 2),
    ("not (len(tag) = 2)", lambda r: not (ok(r["tag"]) and len(r["tag"]) == 2)),
    ("cnt between 0 and 300", lambda r: ok(r["cnt"]) and 0 <= r["cnt"] <= 300),
    ("isnan(hum)", lambda r: ok(r["hum"]) and math.isnan(r["hum"])),
    ("flag", lambda r: r["flag"] is True),
    ("not flag", lambda r: r["flag"] is not True),
    ("flag = false", lambda r: r["flag"] is False),
    ("flag and temp > 0", lambda r: r["flag"] is True and r["temp"] > 0),
]


@pytest.mark.parametrize("expr,fn", EXPRS, ids=[e for e, _ in EXPRS])
def test_expressions_with_nulls(expr, fn):
    rd = ArchiveReader(fx("fixture_obs_v3.tsa"))
    q = rd.query(where=expr)
    t = obs_table()
    assert q == t.take(_py(fn))


def test_resample_with_nulls(tmp_path):
    t = obs_table()
    every = 10 * SEC
    r = resample(t, every, {"hum": ["mean", "count", "max"], "cnt": "min", "temp": "min"})
    assert r.schema.to_text() == "ts:ts,hum_mean:float?,hum_count:int,hum_max:float?,cnt_min:int?,temp_min:float"
    buckets = {}
    for row in t.to_dicts():
        buckets.setdefault((row["ts"] // every) * every, []).append(row)
    keys = sorted(buckets)
    assert r.column("ts") == keys
    for k, mean, count, mx, sm in zip(keys, r.column("hum_mean"), r.column("hum_count"),
                                      r.column("hum_max"), r.column("cnt_min")):
        hums = [x["hum"] for x in buckets[k] if x["hum"] is not None]
        cnts = [x["cnt"] for x in buckets[k] if x["cnt"] is not None]
        assert count == len(hums)
        if not hums:
            assert mean is None and mx is None
        else:
            exp = math.fsum(hums) / len(hums)
            assert (math.isnan(mean) and math.isnan(exp)) or mean == exp
            real = [h for h in hums if not math.isnan(h)]
            assert mx == (max(real) if real else None)
        assert sm == (min(cnts) if cnts else None)
    p = tmp_path / "r.tsa"
    write_archive(p, r)
    assert read_table(p) == r


def test_resample_all_null_bucket():
    t = tbl("ts:ts,h:float?", [0, 1, 20, 21], [None, None, 1.0, 3.0])
    r = resample(t, 10, {"h": ["mean", "first", "count"]})
    assert r.column("h_mean") == [None, 2.0]
    assert r.column("h_first") == [None, 1.0]
    assert r.column("h_count") == [0, 2]


# --- verify and CLI ---------------------------------------------------------------------------

def test_verify_lines(tmp_path, capsys):
    bad = base_archive()
    bad.chunks[2].crc = 5
    pb = put(tmp_path, bad.to_bytes(), "bad.tsa")
    good = fx("fixture_obs_v3.tsa")
    v1 = fx("fixture_weather_v1.tsa")
    v2 = fx("fixture_weather_v2.tsa")
    rc, out, _ = run(capsys, "verify", good, v1, v2, pb)
    assert rc == 1
    assert out.splitlines() == [
        f"{good}: ok (v3, 260 rows, 6 chunks)",
        f"{v1}: ok (v1, 300 rows)",
        f"{v2}: ok (v2, 300 rows)",
        f"{pb}: CORRUPT: chunk 2: checksum mismatch",
    ]
    rc, out, _ = run(capsys, "verify", good, fx("fixture_weather_v3.tsa"))
    assert rc == 0


def test_info_v3_exact(capsys, monkeypatch):
    p = fx("fixture_obs_v3.tsa")
    size = p.stat().st_size
    c = Counter(monkeypatch)
    rc, out, _ = run(capsys, "info", p)
    assert rc == 0 and c.calls == 0
    schema, cols, _ = obs_expected()
    from tsarc.timeutil import format_ts

    assert out.splitlines() == [
        f"file: {p}",
        "version: 3",
        f"size: {size} bytes ({size / 1024:.1f} KiB)",
        "rows: 260",
        "chunks: 6 (chunk_rows 50)",
        "columns: 7",
        "  ts    ts",
        "  temp  float",
        "  hum   float?",
        "  cnt   int?",
        "  tag   str?",
        "  flag  bool?",
        "  note  str",
        f"range: {format_ts(min(cols[0]))} .. {format_ts(max(cols[0]))}",
        "metadata:",
        "  kind = obs",
        "  empty = ",
        "encodings:",
        "  ts    delta2",
        "  temp  xor, plain",
        "  hum   xor, null",
        "  cnt   varint",
        "  tag   dict, null",
        "  flag  bitpack",
        "  note  plain",
    ]


def test_info_empty_v3_and_v2(tmp_path, capsys):
    p = tmp_path / "e.tsa"
    write_archive(p, tbl("ts:ts,value:float?"))
    rc, out, _ = run(capsys, "info", p)
    lines = out.splitlines()
    assert lines[3:5] == ["rows: 0", "chunks: 0 (chunk_rows 1024)"]
    assert lines[-6:] == ["  value  float?", "range: -", "metadata: -", "encodings:", "  ts     -",
                          "  value  -"]
    rc, out, _ = run(capsys, "info", fx("fixture_weather_v2.tsa"))
    lines = out.splitlines()
    assert lines[3] == "rows: 300" and lines[4] == "columns: 5"
    assert "encodings:" not in lines and not any(x.startswith("chunks:") for x in lines)


def test_cli_migrate(tmp_path, capsys):
    out = tmp_path / "m.tsa"
    rc, text, _ = run(capsys, "migrate", fx("fixture_weather_v2.tsa"), out, "--chunk-rows", "64")
    assert rc == 0 and text == f"migrated 300 rows to {out} (5 chunks)\n"
    assert out.read_bytes() == fx("fixture_weather_v3_c64.tsa").read_bytes()
    rc, text, _ = run(capsys, "migrate", fx("fixture_weather_v1.tsa"), out)
    assert rc == 0 and text == f"migrated 300 rows to {out} (1 chunks)\n"
    rc, _, err = run(capsys, "migrate", tmp_path / "missing.tsa", out)
    assert rc == 2


def test_cli_add_column(tmp_path, capsys):
    p = tmp_path / "a.tsa"
    shutil_copy(fx("fixture_weather_v3.tsa"), p)
    rc, text, _ = run(capsys, "add-column", p, "hum:float?")
    assert rc == 0 and text == f"added column hum:float? to {p}\n"
    assert ArchiveReader(p).schema.names[-1] == "hum"
    rc, _, err = run(capsys, "add-column", p, "x:int")
    assert rc == 2 and "a new column must be nullable" in err
    q = tmp_path / "b.tsa"
    shutil_copy(fx("fixture_weather_v2.tsa"), q)
    rc, _, _ = run(capsys, "add-column", q, "x:int?")
    assert rc == 2 and q.read_bytes() == fx("fixture_weather_v2.tsa").read_bytes()


def test_cli_import_defaults_v3(tmp_path, capsys):
    csv_path = tmp_path / "in.csv"
    csv_path.write_text("ts:ts,h:float?,s:str\n2026-03-01T00:00:00Z,1.5,a\n2026-03-01T00:00:01Z,,b\n"
                        "2026-03-01T00:00:02Z,2.5,c\n", encoding="utf-8")
    out = tmp_path / "o.tsa"
    rc, text, _ = run(capsys, "import", csv_path, out, "--chunk-rows", "2", "--meta", "a=b")
    assert rc == 0
    rd = ArchiveReader(out)
    assert rd.version == 3 and rd.chunk_rows == 2 and rd.chunk_count == 2
    expect = tbl("ts:ts,h:float?,s:str", [T0, T0 + SEC, T0 + 2 * SEC], [1.5, None, 2.5], ["a", "b", "c"])
    assert out.read_bytes() == spec_bytes(expect, {"a": "b"}, 2)
    rc, text, _ = run(capsys, "export", out)
    assert text == csv_path.read_text(encoding="utf-8")
    rc, _, _ = run(capsys, "import", csv_path, tmp_path / "v2.tsa", "--format-version", "2")
    assert rc == 2 and not (tmp_path / "v2.tsa").exists()


def test_cli_convert_chunk_rows(tmp_path, capsys):
    out = tmp_path / "c.tsa"
    rc, text, _ = run(capsys, "convert", fx("fixture_weather_v2.tsa"), out, "--format-version", "3",
                      "--chunk-rows", "64")
    assert rc == 0 and out.read_bytes() == fx("fixture_weather_v3_c64.tsa").read_bytes()
    rc, _, _ = run(capsys, "convert", out, tmp_path / "x.tsa", "--format-version", "4")
    assert rc == 2 and not (tmp_path / "x.tsa").exists()


def test_cli_query_and_stats_on_v3(tmp_path, capsys):
    p = fx("fixture_obs_v3.tsa")
    rc, out, _ = run(capsys, "query", p, "--where", "hum > 10", "--format", "count")
    assert rc == 0 and int(out) == len(_py(lambda r: ok(r["hum"]) and r["hum"] > 10))
    rc, out, _ = run(capsys, "stats", p)
    assert rc == 0 and "nulls=50" in out
    rc, out, _ = run(capsys, "export", p, "--format", "jsonl")
    assert rc == 0 and out.splitlines()[0].count("null") >= 2


def test_cli_merge_default_v3(tmp_path, capsys):
    out = tmp_path / "m.tsa"
    rc, _, _ = run(capsys, "merge", out, fx("fixture_weather_v2.tsa"), fx("fixture_weather_v3_c64.tsa"))
    assert rc == 0
    rd = ArchiveReader(out)
    assert rd.version == 3 and rd.num_rows == 600 and rd.table.is_time_sorted()
    rc, _, _ = run(capsys, "merge", tmp_path / "m2.tsa", fx("fixture_weather_v2.tsa"),
                   "--format-version", "2")
    assert rc == 0 and (tmp_path / "m2.tsa").read_bytes() == fx("fixture_weather_v2.tsa").read_bytes()


def test_existing_query_on_v3_matches_v2(tmp_path):
    a = ArchiveReader(fx("fixture_weather_v2.tsa"))
    b = ArchiveReader(fx("fixture_weather_v3_c64.tsa"))
    assert a.table == b.table
    for kw in (dict(start=T0 + 600 * SEC, end=T0 + 3000 * SEC),
               dict(where="site = 'roof' and pressure > 100000", columns=["site", "pressure"]),
               dict(start=T0 + 100 * SEC, where="isnan(temp) or temp > 20")):
        assert a.query(**kw) == b.query(**kw)


# --- existing behaviour keeps working --------------------------------------------------------

def test_existing_ops_cli_on_v3(tmp_path, capsys):
    src = fx("fixture_weather_v3_c64.tsa")
    base = ArchiveReader(fx("fixture_weather_v2.tsa")).table
    rc, out, _ = run(capsys, "dedupe", src, tmp_path / "d.tsa", "--columns", "site")
    assert rc == 0 and out == f"kept {len(set(base.column('site')))} of 300 rows\n"
    assert ArchiveReader(tmp_path / "d.tsa").version == 3
    rc, out, _ = run(capsys, "resample", src, tmp_path / "r.tsa", "--every", "10m", "--agg", "pressure=max")
    assert rc == 0
    r = read_table(tmp_path / "r.tsa")
    assert r == resample(base, 600 * SEC, {"pressure": "max"})
    rc, out, _ = run(capsys, "head", src, "-n", "2")
    assert out.splitlines()[0] == "ts:ts,temp:float,pressure:int,site:str,ok:bool"
    assert out == run(capsys, "head", fx("fixture_weather_v2.tsa"), "-n", "2")[1]


def test_existing_expression_errors_still_exit_2(tmp_path, capsys):
    rc, _, err = run(capsys, "query", fx("fixture_obs_v3.tsa"), "--where", "hum >")
    assert rc == 2 and err.startswith("tsarc: ")
    rc, _, err = run(capsys, "query", fx("fixture_obs_v3.tsa"), "--where", "nosuch = 1")
    assert rc == 2


def test_v1_still_rejects_bool_and_metadata(tmp_path):
    with pytest.raises(NotRepresentableError) as ei:
        write_archive(tmp_path / "x.tsa", GOLDEN["bools"], version=1)
    assert ei.value.column == "b"
    with pytest.raises(NotRepresentableError):
        write_archive(tmp_path / "x.tsa", GOLDEN["str_plain"], {"a": "b"}, version=1)
    assert not (tmp_path / "x.tsa").exists()


def test_v2_v1_csv_export_unchanged(capsys):
    rc, out, _ = run(capsys, "export", fx("fixture_weather_v1.tsa"))
    t = ArchiveReader(fx("fixture_weather_v1.tsa")).table
    assert out == csvio.table_to_csv_text(t)
    assert out.splitlines()[0] == "ts:ts,temp:float,pressure:int,site:str"


def test_ls_and_diff_across_versions(tmp_path, capsys):
    for name in ("fixture_weather_v2.tsa", "fixture_weather_v3_c64.tsa"):
        shutil_copy(fx(name), tmp_path / name)
    rc, out, _ = run(capsys, "diff", tmp_path / "fixture_weather_v2.tsa", tmp_path / "fixture_weather_v3_c64.tsa")
    assert rc == 0 and out == "identical\n"
    rc, out, _ = run(capsys, "ls", tmp_path)
    lines = out.splitlines()
    assert rc == 0 and len(lines) == 4
    assert lines[2].split()[:3] == ["fixture_weather_v2.tsa", "2", "300"]
    assert lines[3].split()[:3] == ["fixture_weather_v3_c64.tsa", "3", "300"]
