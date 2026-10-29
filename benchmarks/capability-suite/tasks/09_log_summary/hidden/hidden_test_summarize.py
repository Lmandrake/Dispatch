import json
import math
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).parent
TRUTH = json.loads((ROOT / "hidden_truth.json").read_text())
KEYS = {"total_lines", "parsed", "corrupt", "by_level", "by_service", "latency_ms", "first_ts", "last_ts", "top_errors"}


def run(path):
    r = subprocess.run([sys.executable, str(ROOT / "summarize.py"), str(path)], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)


@pytest.fixture(scope="module")
def out():
    return run(ROOT / "logs" / "app.log")


def test_schema(out):
    assert set(out) == KEYS
    assert set(out["by_level"]) == {"DEBUG", "INFO", "WARN", "ERROR"}
    assert set(out["latency_ms"]) == {"count", "min", "max", "mean", "p95"}


@pytest.mark.parametrize("key", ["total_lines", "parsed", "corrupt", "by_level", "by_service", "first_ts", "last_ts"])
def test_exact_fields(out, key):
    assert out[key] == TRUTH[key]


def test_latency(out):
    got, want = out["latency_ms"], TRUTH["latency_ms"]
    assert got["count"] == want["count"]
    for k in ("min", "max", "mean", "p95"):
        assert math.isclose(float(got[k]), want[k], abs_tol=0.011), k


def test_top_errors(out):
    assert [list(x) for x in out["top_errors"]] == TRUTH["top_errors"]


def test_importable(out):
    sys.path.insert(0, str(ROOT))
    import summarize
    assert summarize.summarize(str(ROOT / "logs" / "app.log")) == out


SMALL = """
2026-01-05T10:00:00Z [warning] api: a latency=10ms
{"ts": "2026-01-05 09:59:59", "level": "ERROR", "service": "db", "msg": "b", "latency_ms": 30}

Jan  5 10:00:02 h1 db[12]: error c latency=0.020s
{"ts": "2026-01-05 10:00:03", "level": "error", "service": "api", "msg": "d"}
2026-01-05T10:00:04Z [TRACE] api: unknown level
{"ts": "2026-01-05 10:00:05", "level": "info", "service": "x"
garbage line
Feb 30 10:00:00 h1 db[1]: INFO impossible date
2026-01-05T10:00:06Z [ERROR] web: e
"""


def test_small_crafted(tmp_path):
    p = tmp_path / "s.log"
    p.write_text(SMALL)
    o = run(p)
    assert o["total_lines"] == 9
    assert o["parsed"] == 5 and o["corrupt"] == 4
    assert o["by_level"] == {"DEBUG": 0, "INFO": 0, "WARN": 1, "ERROR": 4}
    assert o["by_service"] == {"api": 2, "db": 2, "web": 1}
    assert o["latency_ms"]["count"] == 3
    assert math.isclose(o["latency_ms"]["min"], 10) and math.isclose(o["latency_ms"]["max"], 30)
    assert math.isclose(o["latency_ms"]["mean"], 20) and math.isclose(o["latency_ms"]["p95"], 30)
    assert o["first_ts"] == "2026-01-05T09:59:59Z" and o["last_ts"] == "2026-01-05T10:00:06Z"
    assert [list(x) for x in o["top_errors"]] == [["db", 2], ["api", 1], ["web", 1]]


def test_empty(tmp_path):
    p = tmp_path / "e.log"
    p.write_text("\n  \n")
    o = run(p)
    assert o["total_lines"] == 0 and o["parsed"] == 0
    assert o["latency_ms"]["count"] == 0 and o["latency_ms"]["p95"] is None
    assert o["first_ts"] is None and o["top_errors"] == []
