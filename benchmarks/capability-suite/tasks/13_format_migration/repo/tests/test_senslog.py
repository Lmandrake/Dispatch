import io
import math
from pathlib import Path

import pytest

from senslog import CorruptFileError, LogReader, Record, UnsupportedVersionError, read_records, write_log
from senslog import csvio, ops, stats
from senslog.cli import main
from senslog.timefmt import format_ts, parse_ts

DATA = Path(__file__).parent / "data"


def sample():
    return [
        Record(1, 1_700_000_000, 21.5, "temp", True),
        Record(2, 1_700_000_001, -7, "Zürich"),
        Record(1, 1_700_000_010, 22.0, "temp", True),
        Record(3, 1_700_000_020, math.inf, ""),
    ]


def test_roundtrip(tmp_path):
    p = tmp_path / "a.slog"
    assert write_log(p, sample(), station="roof", created=1_699_999_000) == 4
    rd = LogReader(p)
    assert rd.version == 1
    assert rd.station == "roof"
    assert rd.created == 1_699_999_000
    assert rd.records == sample()
    assert rd.sensors() == [1, 2, 3]
    assert len(rd.between(1_700_000_001, 1_700_000_020)) == 2


def test_fixture_reads():
    rd = LogReader(DATA / "station_v1.slog")
    assert len(rd) == 600
    assert rd.station == "Mt Wilson Höhe"
    assert LogReader(DATA / "empty_v1.slog").records == []


def test_fixture_rewrite_identical(tmp_path):
    src = DATA / "station_v1.slog"
    rd = LogReader(src)
    out = tmp_path / "b.slog"
    write_log(out, rd.records, station=rd.station, created=rd.created)
    assert out.read_bytes() == src.read_bytes()


def test_checksum_detects_corruption(tmp_path):
    data = bytearray((DATA / "station_v1.slog").read_bytes())
    data[100] ^= 0x01
    p = tmp_path / "bad.slog"
    p.write_bytes(bytes(data))
    with pytest.raises(CorruptFileError):
        LogReader(p)


def test_unknown_version(tmp_path):
    data = bytearray((DATA / "empty_v1.slog").read_bytes())
    data[4] = 9
    p = tmp_path / "v9.slog"
    p.write_bytes(bytes(data))
    with pytest.raises(UnsupportedVersionError):
        LogReader(p)


def test_label_limits(tmp_path):
    with pytest.raises(ValueError):
        write_log(tmp_path / "x.slog", [Record(1, 1, 1, "x" * 25)], created=1)
    with pytest.raises(ValueError):
        write_log(tmp_path / "y.slog", [Record(1, 1, 1, "日本")], created=1)


def test_record_validation():
    with pytest.raises(ValueError):
        Record(70000, 1, 1)
    with pytest.raises(TypeError):
        Record(1, 1, True)
    with pytest.raises(ValueError):
        Record(1, 1, 2 ** 63)


def test_timefmt():
    assert format_ts(0) == "1970-01-01T00:00:00Z"
    assert parse_ts("1970-01-01T00:01:00Z") == 60
    assert parse_ts("1234") == 1234


def test_csv_roundtrip():
    text = csvio.records_to_csv_text(sample())
    assert text.splitlines()[0] == "sensor,timestamp,value,label,calibrated"
    assert csvio.records_from_csv_text(text) == sample()


def test_csv_errors():
    with pytest.raises(csvio.CsvImportError) as ei:
        csvio.records_from_csv_text("sensor,timestamp,value\n1,0,1\n2,bogus,3\n")
    assert ei.value.line == 3


def test_stats():
    s = stats.summarize(sample())
    assert s[1].count == 2 and s[1].mean == pytest.approx(21.75)
    assert s[1].span == 10 and s[1].rate == pytest.approx(0.1)
    assert s[3].rate is None
    assert "sensor" in stats.format_table(s)


def test_ops():
    a = sample()
    assert list(ops.filter_records(a, sensors=[1])) == [a[0], a[2]]
    assert list(ops.filter_records(a, calibrated=False)) == [a[1], a[3]]
    m = ops.merge(a, list(reversed(a)))
    assert len(m) == 8 and ops.is_sorted(m)
    assert ops.dedupe(m) == sorted(a, key=ops.sort_key)


def test_cli(tmp_path, capsys):
    csvp = tmp_path / "in.csv"
    csvp.write_text(csvio.records_to_csv_text(sample()), encoding="utf-8")
    out = tmp_path / "o.slog"
    assert main(["import", str(csvp), str(out), "--station", "roof", "--created", "0"]) == 0
    assert read_records(out) == sample()
    capsys.readouterr()
    assert main(["info", str(out)]) == 0
    assert "records: 4" in capsys.readouterr().out
    f = tmp_path / "f.slog"
    assert main(["filter", str(out), str(f), "--sensor", "1"]) == 0
    assert len(read_records(f)) == 2
    m = tmp_path / "m.slog"
    assert main(["merge", str(m), str(out), str(f), "--dedupe"]) == 0
    assert len(read_records(m)) == 4
    capsys.readouterr()
    assert main(["verify", str(out), str(DATA / "station_v1.slog")]) == 0
    bad = tmp_path / "bad.slog"
    bad.write_bytes(out.read_bytes()[:-1])
    assert main(["verify", str(bad)]) == 1
    assert "CORRUPT" in capsys.readouterr().out
