import hashlib
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from relaylog.sim import events  # noqa: E402

LINE = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z) (DEBUG|INFO|WARN|ERROR) (\{.*\})$")
GOOD_SHA = "0c1be4828e6bef0e945d3f388852113f88600a26625f5402cac978154991f709"


def _output():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "replay.py")], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr[-2000:]
    return r.stdout.splitlines(keepends=True)


def test_every_line_well_formed():
    lines = _output()
    assert len(lines) == 20000
    bad = []
    for ln in lines:
        m = LINE.match(ln.rstrip("\n"))
        try:
            obj = json.loads(m.group(3)) if m else None
        except json.JSONDecodeError:
            obj = None
        if not isinstance(obj, dict) or "kind" not in obj:
            bad.append(ln)
    assert bad == [], bad[:3]


def test_previously_bad_records_keep_their_fields():
    missing = {e["seq"] for e in events() if e["kind"] == "retry" and e["delay"] is None}
    assert missing
    seen = 0
    for ln in _output():
        obj = json.loads(ln.split(" ", 2)[2])
        if obj["kind"] == "retry" and obj["seq"] in missing:
            seen += 1
            assert obj.get("delay_ms", None) is None
            assert isinstance(obj["attempt"], int)
            assert ln.split(" ", 2)[1] == "WARN"
    assert seen == len(missing)


def test_all_other_records_byte_identical():
    missing = {e["seq"] for e in events() if e["kind"] == "retry" and e["delay"] is None}
    h = hashlib.sha256()
    for ln in _output():
        obj = json.loads(ln.split(" ", 2)[2])
        if obj["kind"] == "retry" and obj["seq"] in missing:
            continue
        h.update(ln.encode())
    assert h.hexdigest() == GOOD_SHA
