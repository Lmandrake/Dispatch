import sys, shutil
import os
from pathlib import Path
import gen19_data as g
REF = Path(os.environ["AGENT_STORAGE_ROOT"]) / "NewHarness/scratch/ref-solutions/19_billing_misdirection"
HID = Path(os.environ["AGENT_STORAGE_ROOT"]) / "NewHarness/scratch/build/19/oct2026"
def dump(files, root):
    if root.exists(): shutil.rmtree(root)
    for k, v in files.items():
        p = root / k; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(v)
dump(g.build("visible"), REF / "data" / "mar2026")
dump(g.build("hidden"), HID)
