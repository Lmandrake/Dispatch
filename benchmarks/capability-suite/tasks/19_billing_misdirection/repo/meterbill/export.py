"""Batch export of a billing run for the ERP and the archive.

``export_run(run, out_dir)`` writes:

    invoices/<number>.txt|.csv|.json   every invoice in all three formats
    journal.csv                        the GL journal (ledger.py)
    recon.txt                          the reconciliation report
    manifest.json                      file names, sizes and SHA-256 digests

The manifest lets the archive verify an export later (``verify_export``).
Files are written with LF line ends and UTF-8, so digests are stable across
platforms.
"""

import hashlib
import json
from pathlib import Path

from .ledger import journal, render_journal_csv
from .reconcile import render_recon
from .render import render

FORMATS = (("text", "txt"), ("csv", "csv"), ("json", "json"))


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    path.write_bytes(data)
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def export_run(run, out_dir):
    out = Path(out_dir)
    manifest = {"cycle": run.cycle, "files": {}}
    for inv in run.invoices:
        for fmt, ext in FORMATS:
            rel = f"invoices/{inv.number}.{ext}"
            manifest["files"][rel] = _write(out / rel, render(inv, fmt))
    manifest["files"]["journal.csv"] = _write(out / "journal.csv", render_journal_csv(journal(run.invoices)))
    manifest["files"]["recon.txt"] = _write(out / "recon.txt",
                                            render_recon(run.cycle, run.reconciliation(), run.ingested))
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def verify_export(out_dir):
    """Problems found re-checking an export against its manifest (empty = intact)."""
    out = Path(out_dir)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    problems = []
    for rel, meta in sorted(manifest["files"].items()):
        p = out / rel
        if not p.exists():
            problems.append(f"missing {rel}")
            continue
        data = p.read_bytes()
        if len(data) != meta["size"] or hashlib.sha256(data).hexdigest() != meta["sha256"]:
            problems.append(f"changed {rel}")
    listed = set(manifest["files"])
    for p in sorted(out.rglob("*")):
        rel = p.relative_to(out).as_posix()
        if p.is_file() and rel != "manifest.json" and rel not in listed:
            problems.append(f"unlisted {rel}")
    return problems
