"""Generate fixtures for bench task 18_format_migration_long.

usage: python3 gen18.py <task_dir> [<ref_solution_dir>]

Part 1 (always): visible v1/v2 fixtures from an encoder written here from docs/FORMAT_v1.md and
docs/FORMAT_v2.md (independent of the package):
  repo/tests/data/{weather_v1,weather_v2,empty_v2}.tsa and hidden/fixture_{...}.tsa copies.
Part 2 (when ref dir given): hidden v3 fixtures written by the reference solution, cross-checked
against the independent spec encoder in hidden/hidden_spec3.py:
  hidden/fixture_weather_v3_c64.tsa   migrate(weather_v2, chunk_rows=64)
  hidden/fixture_weather_v3.tsa       migrate(weather_v2) (default chunk_rows)
  hidden/fixture_obs_v3.tsa           nullable/edge-case table, chunk_rows=50
  hidden/fixture_obs.json             the obs table's values
"""
import json
import math
import random
import struct
import sys
import zlib
from pathlib import Path

T = Path(sys.argv[1])
REF = Path(sys.argv[2]) if len(sys.argv) > 2 else None
T0 = 1_772_323_200_000_000
SITES = ["roof", "yard", "Zürich roof", "", "ß", "lab-2", "north mast"]


def crc(b):
    return zlib.crc32(b) & 0xFFFFFFFF


def weather_rows(n=300, seed=18):
    rnd = random.Random(seed)
    t = T0
    rows = []
    specials = [math.inf, -math.inf, -0.0, 0.0, math.nan, 5e-324, -1.5e300]
    for i in range(n):
        t += rnd.choice([0, 1, 1, 2, 5, 30, 60, 60, 60]) * 1_000_000 + rnd.choice([0, 0, 0, 250_000])
        if i < len(specials):
            temp = specials[i]
        elif rnd.random() < 0.05:
            temp = math.nan
        else:
            temp = round(rnd.gauss(14, 6), rnd.choice([1, 1, 2, 6]))
        pressure = rnd.choice([101325, 101300, 99800, -1, 0, 2 ** 40]) if i % 37 == 0 else \
            100000 + rnd.randint(-2000, 2000)
        site = rnd.choice(SITES)
        ok = rnd.random() < 0.8
        rows.append((t, temp, pressure, site, ok))
    return rows


TYPES = {"ts": 1, "int": 2, "float": 3, "str": 4, "bool": 5}


def v1_bytes(cols, rows):
    b = b"TSAR" + struct.pack("<HHHI", 1, 0, len(cols), len(rows))
    for name, ty in cols:
        b += struct.pack("<BB", TYPES[ty], len(name)) + name.encode()
    for r in rows:
        for (name, ty), v in zip(cols, r):
            if ty == "float":
                b += struct.pack("<d", v)
            elif ty == "str":
                e = v.encode("latin-1")
                b += struct.pack("<H", len(e)) + e
            else:
                b += struct.pack("<q", v)
    return b + struct.pack("<I", crc(b))


def u16s(s):
    e = s.encode("utf-8")
    return struct.pack("<H", len(e)) + e


def v2_bytes(cols, rows, meta):
    h = b"TSAR" + struct.pack("<HHIHH", 2, 0, len(rows), len(cols), len(meta))
    for k, v in meta.items():
        h += u16s(k) + u16s(v)
    out = h + struct.pack("<I", crc(h))
    for j, (name, ty) in enumerate(cols):
        vals = [r[j] for r in rows]
        if ty in ("ts", "int"):
            d = b"".join(struct.pack("<q", v) for v in vals)
        elif ty == "float":
            d = b"".join(struct.pack("<d", v) for v in vals)
        elif ty == "str":
            blobs = [v.encode() for v in vals]
            ends, e = [], 0
            for x in blobs:
                e += len(x)
                ends.append(struct.pack("<I", e))
            d = b"".join(ends) + b"".join(blobs)
        else:
            bm = bytearray((len(vals) + 7) // 8)
            for i, v in enumerate(vals):
                if v:
                    bm[i >> 3] |= 0x80 >> (i & 7)
            d = bytes(bm)
        out += struct.pack("<BB", TYPES[ty], len(name)) + name.encode() + struct.pack("<I", len(d)) \
            + d + struct.pack("<I", crc(d))
    return out + b"RAST"


rows = weather_rows()
cols2 = [("ts", "ts"), ("temp", "float"), ("pressure", "int"), ("site", "str"), ("ok", "bool")]
meta = {"station": "Mt Wilson", "source": "gen18", "units.temp": "°C"}
w1 = v1_bytes(cols2[:4], [r[:4] for r in rows])
w2 = v2_bytes(cols2, rows, meta)
e2 = v2_bytes([("ts", "ts"), ("v", "float")], [], {})
data = T / "repo/tests/data"
data.mkdir(parents=True, exist_ok=True)
hidden = T / "hidden"
for name, b in (("weather_v1.tsa", w1), ("weather_v2.tsa", w2), ("empty_v2.tsa", e2)):
    (data / name).write_bytes(b)
    (hidden / f"fixture_{name}").write_bytes(b)
print("part 1:", len(w1), len(w2), len(e2))

if REF is None:
    sys.exit(0)

# ---- part 2: v3 fixtures from the reference solution --------------------------------------
sys.path.insert(0, str(REF))
sys.dont_write_bytecode = True
sys.path.insert(0, str(hidden))
import tsarc  # noqa: E402
from tsarc import Schema, Table, migrate, write_archive, ArchiveReader  # noqa: E402
import hidden_spec3 as S  # noqa: E402

assert tsarc.__file__.startswith(str(REF)), tsarc.__file__
src = hidden / "fixture_weather_v2.tsa"
for name, cr in (("fixture_weather_v3_c64.tsa", 64), ("fixture_weather_v3.tsa", None)):
    out = hidden / name
    if cr is None:
        migrate(src, out)
    else:
        migrate(src, out, chunk_rows=cr)
    expect = S.encode_v3([(n, t, False) for n, t in cols2], [list(c) for c in zip(*rows)], meta,
                         cr or 1024)
    assert out.read_bytes() == expect, name


def obs_columns(n=260, seed=7):
    rnd = random.Random(seed)
    ts, temp, hum, cnt, tag, flag, note = [], [], [], [], [], [], []
    t = -5_000_000
    for i in range(n):
        t += rnd.choice([1, 1, 1, 7, 1000, 1_000_000])
        ts.append(t)
        temp.append(rnd.choice([1.0, 1.0, 1.5, -0.0, 0.0, math.nan, 2.25]) if i < 100 else
                    round(rnd.uniform(-5, 5), 3))
        # hum: chunk 0 (rows 0-49) partly null, chunk 1 (50-99) all null, others mixed / full
        if 50 <= i < 100:
            hum.append(None)
        elif i < 50:
            hum.append(None if i % 3 == 0 else float(i))
        else:
            hum.append(None if rnd.random() < 0.1 else rnd.choice([math.nan, 0.5, 60.0]))
        cnt.append(None if i % 11 == 0 else rnd.choice([0, -1, 1, 2 ** 62, -(2 ** 63), 300]))
        tag.append(None if 200 <= i < 250 else rnd.choice(["a", "bb", "ccc", "Ω", ""]))
        flag.append(None if i % 5 == 0 else rnd.random() < 0.5)
        note.append(f"n{i:04d}-{rnd.randint(0, 10**9)}")
    return [ts, temp, hum, cnt, tag, flag, note]


obs_cols = [("ts", "ts", False), ("temp", "float", False), ("hum", "float", True),
            ("cnt", "int", True), ("tag", "str", True), ("flag", "bool", True),
            ("note", "str", False)]
oc = obs_columns()
schema = Schema.parse(",".join(f"{n}:{t}{'?' if nl else ''}" for n, t, nl in obs_cols))
table = Table(schema, oc)
obs_meta = {"kind": "obs", "empty": ""}
out = hidden / "fixture_obs_v3.tsa"
write_archive(out, table, obs_meta, chunk_rows=50)
assert out.read_bytes() == S.encode_v3(obs_cols, oc, obs_meta, 50), "obs"
assert ArchiveReader(out).table == table


def jv(v):
    if isinstance(v, float):
        return {"f": float.hex(v)}
    return v


(hidden / "fixture_obs.json").write_text(json.dumps({
    "schema": schema.to_text(), "metadata": obs_meta,
    "columns": [[jv(v) for v in col] for col in oc]}, ensure_ascii=False))
print("part 2 ok")
