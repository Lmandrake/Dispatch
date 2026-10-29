from pathlib import Path

import pytest

from tsarc import ArchiveReader, read_table, write_archive
from tsarc.cli import main

from .helpers import weather

DATA = Path(__file__).parent / "data"


def run(capsys, *argv):
    rc = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return rc, out, err


def test_info(capsys, tmp_path):
    p = tmp_path / "w.tsa"
    write_archive(p, weather(50), {"source": "lab"})
    rc, out, _ = run(capsys, "info", p)
    assert rc == 0
    lines = out.splitlines()
    assert lines[1] == "version: 2"
    assert lines[3] == "rows: 50"
    assert lines[4] == "columns: 4"
    assert lines[5] == "  ts    ts"
    assert lines[9] == "range: 2026-03-01T00:00:00Z .. 2026-03-01T00:49:00Z"
    assert lines[10:] == ["metadata:", "  source = lab"]


def test_import_export(capsys, tmp_path):
    t = weather(20)
    csv_path = tmp_path / "in.csv"
    from tsarc import csvio

    csvio.write_csv_file(csv_path, t)
    out = tmp_path / "o.tsa"
    rc, text, _ = run(capsys, "import", csv_path, out, "--meta", "a=b")
    assert rc == 0 and text.strip() == f"imported 20 rows into {out}"
    rd = ArchiveReader(out)
    assert rd.table == t and rd.metadata == {"a": "b"}
    rc, text, _ = run(capsys, "export", out)
    assert text == csv_path.read_text()


def test_query_count(capsys, tmp_path):
    p = tmp_path / "w.tsa"
    write_archive(p, weather(60))
    rc, out, _ = run(capsys, "query", p, "--start", "2026-03-01T00:30:00Z", "--format", "count")
    assert (rc, out) == (0, "30\n")
    rc, out, err = run(capsys, "query", p, "--where", "bogus >")
    assert rc == 2 and err.startswith("tsarc: ")


def test_verify(capsys, tmp_path):
    good = tmp_path / "g.tsa"
    write_archive(good, weather(5))
    bad = tmp_path / "b.tsa"
    data = bytearray(good.read_bytes())
    data[-10] ^= 1
    bad.write_bytes(bytes(data))
    rc, out, _ = run(capsys, "verify", good, DATA / "weather_v1.tsa", bad)
    lines = out.splitlines()
    assert rc == 1
    assert lines[0] == f"{good}: ok (v2, 5 rows)"
    assert lines[1] == f"{DATA / 'weather_v1.tsa'}: ok (v1, 300 rows)"
    assert lines[2].startswith(f"{bad}: CORRUPT: ")


def test_convert_and_merge(capsys, tmp_path):
    p = tmp_path / "w.tsa"
    write_archive(p, weather(10))
    rc, out, _ = run(capsys, "convert", p, tmp_path / "w1.tsa", "--format-version", "1")
    assert rc == 0 and ArchiveReader(tmp_path / "w1.tsa").version == 1
    rc, out, _ = run(capsys, "merge", tmp_path / "m.tsa", p, tmp_path / "w1.tsa")
    assert rc == 0 and read_table(tmp_path / "m.tsa").num_rows == 20
    rc, _, err = run(capsys, "convert", DATA / "weather_v2.tsa", tmp_path / "x.tsa",
                     "--format-version", "1")
    assert rc == 2 and "metadata" in err


def test_stats_cli(capsys):
    rc, out, _ = run(capsys, "stats", DATA / "weather_v2.tsa")
    assert rc == 0
    assert out.splitlines()[-1].startswith("time: 2026-03-01T00:00:")


def test_meta_and_diff(capsys, tmp_path):
    p = tmp_path / "w.tsa"
    write_archive(p, weather(10))
    rc, out, _ = run(capsys, "meta", p, "--set", "x=1")
    assert out.splitlines() == ["metadata:", "  x = 1"]
    q = tmp_path / "q.tsa"
    write_archive(q, weather(10))
    assert run(capsys, "diff", p, q)[0] == 0
    write_archive(q, weather(11))
    rc, out, _ = run(capsys, "diff", p, q)
    assert rc == 1 and "row count differs: 10 vs 11" in out
