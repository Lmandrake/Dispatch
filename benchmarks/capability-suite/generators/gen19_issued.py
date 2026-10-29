"""Write data/<set>/issued/*.json: the prior cycle's invoices as the BUGGY engine issued them."""
import json, subprocess, sys, shutil
import os
from pathlib import Path
B = Path(os.environ["AGENT_STORAGE_ROOT"]) / "NewHarness/scratch/build/19"
REF = Path(os.environ["AGENT_STORAGE_ROOT"]) / "NewHarness/scratch/ref-solutions/19_billing_misdirection"
SNIP = r'''
import sys, json
from meterbill.pipeline import run_billing
from meterbill.render import render
run = run_billing(sys.argv[1], sys.argv[2])
print(json.dumps({i.number: render(i, "json") for i in run.invoices}))
'''
def issued(data_dir, cycles, paid):
    """paid: invoice number -> paid_on date text ('' = unpaid); unlisted -> paid on due date."""
    out = Path(data_dir) / "issued"
    if out.exists(): shutil.rmtree(out)
    out.mkdir()
    names = []
    import csv, io
    rp = Path(data_dir) / "receivables.csv"
    for cycle in cycles:
        rows = []
        p = subprocess.run([sys.executable, "-c", SNIP, str(data_dir), cycle], cwd=B / "buggy", capture_output=True, text=True, check=True)
        docs = json.loads(p.stdout)
        for num, text in sorted(docs.items()):
            (out / f"{num}.json").write_text(text, encoding="utf-8")
            names.append(num)
            d = json.loads(text)
            paid_on = paid.get(num, d["due_date"])
            if d["amount_due"].strip("0.") == "":
                continue
            rows.append([num, d["customer"]["id"], d["currency"], d["amount_due"], d["due_date"], paid_on])
        buf = io.StringIO(); w = csv.writer(buf, lineterminator="\n")
        for r in rows: w.writerow(r)
        rp.write_text(rp.read_text() + buf.getvalue())
    return names
VIS_UNPAID = {"KC-2026-01-C04": "", "KC-2026-01-C05": "", "KC-2026-01-C12": "", "KC-2026-02-C01": "",
              "KC-2026-01-C10": "2026-03-20", "KC-2026-02-C06": "", "KC-2026-02-C08": "", "KC-2026-02-C14": ""}
HID_UNPAID = {"KC-2026-08-C04": "", "KC-2026-08-C13": "", "KC-2026-08-C10": "2026-10-02", "KC-2026-08-C07": "",
              "KC-2026-09-C02": "", "KC-2026-09-C09": "", "KC-2026-08-C08": "", "KC-2026-09-C14": ""}
print(issued(REF / "data/mar2026", ["2026-01", "2026-02"], VIS_UNPAID))
print(issued(B / "oct2026", ["2026-08", "2026-09"], HID_UNPAID))
