"""Generate task 06 repo/calibration.py and hidden test with AST hashes."""
import ast, hashlib, json, random, sys, pathlib
T = pathlib.Path(sys.argv[1])
rnd = random.Random(6)
N = 145
TARGET = "calibrate_s070"
gains = [round(rnd.uniform(0.01, 0.09), 4) for _ in range(N)]
gains[71] = gains[70]; gains[7] = gains[70]  # shared literal traps
lines = ['"""Sensor calibration routines.',
         '',
         'GENERATED from the bench calibration sheet (rev 14). Each sensor has its own',
         'routine because the vendor curves differ in small ways; keep them separate.',
         '"""',
         '',
         'LOW_LIMIT = 0.0', 'HIGH_LIMIT = 4095.0', '', '']
for i in range(N):
    sid = f"S{i:03d}"
    off = round(rnd.uniform(0, 40), 2); g = gains[i]; b = round(rnd.uniform(-5, 5), 3)
    nd = rnd.choice([3, 4])
    lines += [f'def calibrate_{sid.lower()}(raw):',
              f'    """Convert a raw {sid} ADC reading to engineering units."""',
              '    if raw is None:',
              '        return None',
              '    x = float(raw)',
              '    if x < LOW_LIMIT or x > HIGH_LIMIT:',
              f'        raise ValueError("{sid} reading out of range: %r" % (raw,))',
              f'    x = x - {off}',
              f'    x = x * {g}',
              f'    x = x + {b}',
              f'    return round(x, {nd})',
              '', '']
lines += ['CALIBRATORS = {']
lines += [f'    "S{i:03d}": calibrate_s{i:03d},' for i in range(N)]
lines += ['}', '', '',
          'def calibrate(sensor_id, raw):',
          '    """Dispatch to the routine for ``sensor_id`` (e.g. "S012")."""',
          '    try:',
          '        fn = CALIBRATORS[sensor_id.upper()]',
          '    except KeyError:',
          '        raise KeyError(f"unknown sensor {sensor_id}") from None',
          '    return fn(raw)', '']
src = "\n".join(lines)
(T / "repo/calibration.py").write_text(src)
tree = ast.parse(src)
hashes = {}
for node in tree.body:
    name = node.name if isinstance(node, (ast.FunctionDef,)) else None
    if name == TARGET:
        continue
    key = name or f"stmt:{ast.dump(node)[:60]}"
    if isinstance(node, ast.Assign):
        key = "assign:" + ",".join(ast.unparse(t) for t in node.targets)
    if isinstance(node, ast.Expr):
        key = "docstring"
    hashes[key] = hashlib.sha256(ast.dump(node).encode()).hexdigest()
# sample expected outputs for every non-target function
ns = {}; exec(src, ns)
samples = [0, 1, 17.5, 100, 2048, 4095]
expected = {f"S{i:03d}": [ns[f"calibrate_s{i:03d}"](v) for v in samples]
            for i in range(N) if f"calibrate_s{i:03d}" != TARGET}
off70 = float([l for l in src.split("def calibrate_s070")[1].splitlines() if "x = x - " in l][0].split("- ")[1])
b70 = float([l for l in src.split("def calibrate_s070")[1].splitlines() if "x = x + " in l][0].split("+ ")[1])
nd70 = int([l for l in src.split("def calibrate_s070")[1].splitlines() if "round(" in l][0].split(", ")[1].rstrip(")"))
wants = [(r, max(0.0, round((r - off70) * 0.0213 - 1.5, nd70))) for r in [0, 10, 36.84, 100, 107.0, 108.0, 120, 500, 2048, 4095]]
info = {"gain": gains[70], "src": ast.get_source_segment(src, [n for n in tree.body if getattr(n, "name", "") == TARGET][0])}
print(json.dumps(info))
hidden = f'''import ast
import hashlib
import math
import pathlib

import pytest
import calibration as cal

SRC = (pathlib.Path(__file__).parent / "calibration.py").read_text()
HASHES = {json.dumps(hashes, indent=1)}
SAMPLES = {samples!r}
EXPECTED = {json.dumps(expected)}
TARGET = "{TARGET}"\nWANTS = {wants!r}


def _nodes():
    out = {{}}
    for node in ast.parse(SRC).body:
        if isinstance(node, ast.FunctionDef):
            key = node.name
        elif isinstance(node, ast.Assign):
            key = "assign:" + ",".join(ast.unparse(t) for t in node.targets)
        elif isinstance(node, ast.Expr):
            key = "docstring"
        else:
            key = "stmt:" + ast.dump(node)[:60]
        out[key] = node
    return out


def test_everything_else_unchanged():
    nodes = _nodes()
    for key, h in HASHES.items():
        assert key in nodes, f"{{key}} missing"
        assert hashlib.sha256(ast.dump(nodes[key]).encode()).hexdigest() == h, f"{{key}} was modified"
    extra = set(nodes) - set(HASHES) - {{TARGET}}
    assert not extra, f"unexpected new top-level definitions: {{extra}}"


@pytest.mark.parametrize("sid", sorted(EXPECTED))
def test_other_sensors_behave_the_same(sid):
    assert [cal.calibrate(sid, v) for v in SAMPLES] == EXPECTED[sid]


def test_target_new_behaviour():
    f = cal.calibrate_s070
    assert cal.CALIBRATORS["S070"] is f
    assert f(None) is None
    for bad in (-1, 4095.5):
        with pytest.raises(ValueError):
            f(bad)
    # new gain, same offset/bias/rounding; negatives clamp to 0.0
    for raw, want in WANTS:
        got = f(raw)
        assert isinstance(got, float)
        assert math.isclose(got, want, abs_tol=1.5e-4), (raw, got, want)
    assert cal.calibrate("s070", 4095) == f(4095)
'''
(T / "hidden/hidden_test_calibration.py").write_text(hidden)
