"""Regenerate task 14 golden files from the reference solution.

usage: python3 gen14.py   (writes repo/tests/golden/q1_month.txt and q1_quarter.csv)
The hidden test embeds the same text literally; re-embed it if goldens change.
"""
import subprocess, sys
import os
from pathlib import Path
REF = Path(os.environ["AGENT_STORAGE_ROOT"]) / "NewHarness/scratch/ref-solutions/14_wrong_module_blame"
OUT = Path.home() / "dev/Dispatch/harnesses/bench/tasks/14_wrong_module_blame/repo/tests/golden"
base = [sys.executable, "-m", "ledgerkit.cli", "data/q1.ledger", "--rates", "data/rates.txt"]
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "q1_month.txt").write_text(subprocess.run(base, cwd=REF, capture_output=True, text=True, check=True).stdout)
(OUT / "q1_quarter.csv").write_text(subprocess.run(base + ["--period", "quarter", "--format", "csv"], cwd=REF, capture_output=True, text=True, check=True).stdout)
