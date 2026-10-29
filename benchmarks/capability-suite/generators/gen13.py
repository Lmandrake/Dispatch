"""Generate the v1 fixtures for bench task 13_format_migration.

usage: python3 gen13.py <task_dir>
Writes repo/tests/data/{station_v1.slog,empty_v1.slog} and hidden/fixture_v1_station.slog,
hidden/fixture_v1_empty.slog, hidden/fixture_v1_station.json (expected records).
Uses its own v1 encoder (independent of the package) so fixtures are spec-derived.
"""
import json
import math
import random
import struct
import sys
import zlib
from pathlib import Path

T = Path(sys.argv[1])
LABELS = ["", "temp", "°C ambient", "Zürich roof", "humidité", "x" * 24, "wind/gust", "Ångström",
          "pressure hPa", "ß", "ñandú pen 3", "rain", "bay-7 spare channel 01"]


def records(n=600, seed=13):
    rnd = random.Random(seed)
    t = 1_650_000_000
    out = []
    specials = [math.inf, -math.inf, -0.0, 0.0, math.nan, 2 ** 63 - 1, -(2 ** 63), 0, 1e-300, -1.5e300]
    for i in range(n):
        t += rnd.choice([0, 0, 1, 1, 2, 5, 30, 60])
        sensor = rnd.choice([1, 2, 3, 7, 42, 300, 65535])
        if i < len(specials):
            value = specials[i]
        elif rnd.random() < 0.5:
            value = round(rnd.gauss(20, 8), rnd.choice([1, 2, 6]))
        else:
            value = rnd.randint(-100000, 100000)
        out.append((sensor, t, value, rnd.choice(LABELS), rnd.random() < 0.3))
    return out


def lat(s, w):
    b = s.encode("latin-1")
    assert len(b) <= w
    return b.ljust(w, b"\0")


def v1_bytes(recs, created, station):
    body = struct.pack("<4sHHII16s", b"SLOG", 1, 0, len(recs), created, lat(station, 16))
    for sensor, ts, value, label, cal in recs:
        if isinstance(value, float):
            kind, vb = 1, struct.pack("<d", value)
        else:
            kind, vb = 0, struct.pack("<q", value)
        body += struct.pack("<HBBI", sensor, kind, 1 if cal else 0, ts) + vb + lat(label, 24)
    return body + struct.pack("<I", zlib.crc32(body) & 0xFFFFFFFF)


recs = records()
station = "Mt Wilson Höhe"
created = 1_650_000_000 - 3600
full = v1_bytes(recs, created, station)
empty = v1_bytes([], 1_600_000_000, "spare")
(T / "repo/tests/data").mkdir(parents=True, exist_ok=True)
for d, pre in [(T / "repo/tests/data", ""), (T / "hidden", "fixture_v1_")]:
    (d / f"{pre}station{'' if pre else '_v1'}.slog").write_bytes(full)
    (d / f"{pre}empty{'' if pre else '_v1'}.slog").write_bytes(empty)


def jv(v):
    return {"float": float.hex(v)} if isinstance(v, float) else {"int": v}


(T / "hidden/fixture_v1_station.json").write_text(json.dumps({
    "station": station, "created": created,
    "records": [[s, ts, jv(v), lab, cal] for s, ts, v, lab, cal in recs]}, ensure_ascii=False))
print(len(full), len(recs))
