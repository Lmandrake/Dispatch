"""Write tests/golden/mar2026/* in the reference from the reference code, and
the hidden goldens for the second dataset into build/19/hidden_goldens.json."""
import json, subprocess, sys
import os
from pathlib import Path
REF = Path(os.environ["AGENT_STORAGE_ROOT"]) / "NewHarness/scratch/ref-solutions/19_billing_misdirection"
HID = Path(os.environ["AGENT_STORAGE_ROOT"]) / "NewHarness/scratch/build/19/oct2026"
SNIP = r'''
import sys, json
from meterbill.pipeline import run_billing
from meterbill.render import render
from meterbill.reconcile import render_recon
run = run_billing(sys.argv[1], sys.argv[2])
out = {}
for i in run.invoices:
    for fmt, ext in (("text", "txt"), ("csv", "csv"), ("json", "json")):
        out[f"{i.number}.{ext}"] = render(i, fmt)
out[f"recon-{sys.argv[2]}.txt"] = render_recon(sys.argv[2], run.reconciliation(), run.ingested)
from meterbill.rebill import rebill, render_rebill_csv, render_rebill_text
adj = rebill(sys.argv[1])
out["rebill.txt"] = render_rebill_text(adj)
out["rebill.csv"] = render_rebill_csv(adj)
from meterbill.restatement import restate, render_summary, render_journal, render_revenue
res = restate(sys.argv[1], sys.argv[4], sys.argv[2])
out["restate-summary.txt"] = render_summary(res)
out["restate-journal.csv"] = render_journal(res)
out["restate-revenue.csv"] = render_revenue(res)
from meterbill.close import close, render_pack
for name, text in render_pack(close(sys.argv[1], sys.argv[4], sys.argv[2])).items():
    out["close-" + name] = text
prev = sys.argv[3]
prun = run_billing(sys.argv[1], prev)
for i in prun.invoices:
    out[f"{i.number}.txt"] = render(i, "text")
print(json.dumps(out))
'''
def gen(d, c, prev):
    first = {"2026-03": "2026-01", "2026-10": "2026-08"}[c]
    p = subprocess.run([sys.executable, "-c", SNIP, str(d), c, prev, first], cwd=REF, capture_output=True, text=True, check=True)
    return json.loads(p.stdout)
vis = gen(REF / "data/mar2026", "2026-03", "2026-02")
g = REF / "tests/golden/mar2026"; g.mkdir(parents=True, exist_ok=True)
for f in g.iterdir(): f.unlink()
keep = [k for k in vis if (k.endswith(".txt") and "2026-02" not in k and "-C14." not in k and not k.startswith("rebill") and not k.startswith("recon") and not k.startswith("restate") and not k.startswith("close-")) or k in ("KC-2026-03-C03.csv", "KC-2026-03-C07.csv", "KC-2026-03-C09.csv",
        "KC-2026-03-C02.json", "KC-2026-03-C08.json", "KC-2026-03-C11.json")]
for k in keep: (g / k).write_text(vis[k], encoding="utf-8")
hid = gen(HID, "2026-10", "2026-09")
(HID.parent / "hidden_goldens.json").write_text(json.dumps({"vis": vis, "hid": hid}))
print(len(keep), "visible goldens;", len(hid), "hidden")
