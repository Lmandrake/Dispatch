import json
import subprocess
import sys

from .helpers import DATA, ROOT


def cli(*args):
    p = subprocess.run([sys.executable, "-m", "meterbill", *args], cwd=ROOT, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def test_rate_command():
    rc, out, _ = cli("rate", str(DATA), "team", "api_calls", "2500000")
    assert rc == 0
    assert out.splitlines()[-1].split()[-2:] == ["775.00000000", "USD"]


def test_rate_unknown_metric_is_an_error():
    rc, _, err = cli("rate", str(DATA), "starter", "seats", "3")
    assert rc == 2 and "no seats charge" in err


def test_invoice_json_for_one_customer():
    rc, out, _ = cli("invoice", str(DATA), "2026-03", "--customer", "C04", "--format", "json")
    assert rc == 0
    doc = json.loads(out)
    assert doc["number"] == "KC-2026-03-C04" and doc["currency"] == "GBP"


def test_invoice_out_dir(tmp_path):
    rc, out, _ = cli("invoice", str(DATA), "2026-03", "--customer", "C04", "--customer", "C11", "--out", str(tmp_path))
    assert rc == 0 and "wrote 2 invoice(s)" in out
    assert sorted(p.name for p in tmp_path.iterdir()) == ["KC-2026-03-C04.txt", "KC-2026-03-C11.txt"]


def test_check_and_aging_commands():
    rc, out, _ = cli("check", str(DATA), "2026-03")
    assert rc == 0 and out.strip().endswith("warning(s)")
    rc, out, _ = cli("aging", str(DATA), "2026-03-31")
    assert rc == 0 and out.startswith("AR aging as of 2026-03-31")


def test_export_and_verify(tmp_path):
    from meterbill.export import verify_export
    rc, out, _ = cli("export", str(DATA), "2026-03", str(tmp_path / "x"))
    assert rc == 0
    assert verify_export(tmp_path / "x") == []
    (tmp_path / "x" / "recon.txt").write_text("tampered\n")
    assert verify_export(tmp_path / "x") == ["changed recon.txt"]


def test_bad_data_dir():
    rc, _, err = cli("recon", str(ROOT / "nope"), "2026-03")
    assert rc == 2 and "not a directory" in err
