"""For each bug alone, all bugs, and all-but-one: which customers' text invoices differ from ref."""
import subprocess, sys, itertools, json
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import gen19_bugs as B
REF = Path(os.environ["AGENT_STORAGE_ROOT"]) / "NewHarness/scratch/ref-solutions/19_billing_misdirection"
TMP = Path(os.environ["AGENT_STORAGE_ROOT"]) / "NewHarness/scratch/build/19/measure"
H = Path(os.environ["AGENT_STORAGE_ROOT"]) / "NewHarness/scratch/build/19/oct2026"
DATA = {"vis": (REF / "data/mar2026", "2026-03"), "visF": (REF / "data/mar2026", "2026-02"),
        "hid": (H, "2026-10"), "hidS": (H, "2026-09")}
SNIP = r'''
import sys, json
sys.path.insert(0, sys.argv[1])
from meterbill.pipeline import run_billing
from meterbill.render import render
from meterbill.reconcile import render_recon
run = run_billing(sys.argv[2], sys.argv[3])
out = {i.customer.id: render(i, "text") + render(i, "json") for i in run.invoices}
out["RECON"] = render_recon(sys.argv[3], run.reconciliation(), run.ingested)
print(json.dumps(out))
'''
def outputs(root, which):
    d, c = DATA[which]
    p = subprocess.run([sys.executable, "-c", SNIP, str(root), str(d), c], capture_output=True, text=True)
    if p.returncode: print(p.stderr); raise SystemExit
    return json.loads(p.stdout)
base = {w: outputs(REF, w) for w in DATA}
def diff(names):
    B.subprocess = None
    import shutil
    if TMP.exists(): shutil.rmtree(TMP)
    shutil.copytree(REF, TMP, ignore=shutil.ignore_patterns("__pycache__", "data"))
    B.apply(TMP, names)
    res = {}
    for w in DATA:
        o = outputs(TMP, w)
        res[w] = sorted(k for k in base[w] if o.get(k) != base[w][k])
    return res
allb = list(B.BUGS)
import sys as _s
only = _s.argv[1:]
for n in (only or allb): print("only", n, diff([n]))
if only: raise SystemExit
print("ALL", diff(allb))
for n in allb: print("all but", n, diff([m for m in allb if m != n]))
