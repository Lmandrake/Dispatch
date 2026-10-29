"""Write hidden/hidden_data.json: both datasets as on disk (file -> text) and all goldens from the reference."""
import json
import os
from pathlib import Path
B = Path(os.environ["AGENT_STORAGE_ROOT"]) / "NewHarness/scratch/build/19"
REF = Path(os.environ["AGENT_STORAGE_ROOT"]) / "NewHarness/scratch/ref-solutions/19_billing_misdirection"
OUT = Path.home() / "dev/Dispatch/harnesses/bench/tasks/19_billing_misdirection/hidden/hidden_data.json"
def snap(d):
    return {p.relative_to(d).as_posix(): p.read_text() for p in sorted(d.rglob("*")) if p.is_file()}
gold = json.loads((B / "hidden_goldens.json").read_text())
doc = {"datasets": {"mar2026": snap(REF / "data/mar2026"), "oct2026": snap(B / "oct2026")},
       "goldens": {"mar2026": gold["vis"], "oct2026": gold["hid"]}}
OUT.write_text(json.dumps(doc, sort_keys=True))
print(OUT, OUT.stat().st_size)
