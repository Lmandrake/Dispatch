"""Per-user settings (~/.config/chatgpt-consult/config.json). No Docker, no network, no Chrome.

Each case imports consult.py in a fresh interpreter, because the settings are read at import.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
REPO = BIN.parent
PROBE = ("import json, consult; print(json.dumps({'ledger': str(consult.LEDGER), "
         "'project': consult.CONTAINER_PROJECT, 'title': consult.thread_title('Machinist')}))")


def load(config_text=None):
    with tempfile.TemporaryDirectory() as tmp:
        cfg = pathlib.Path(tmp) / "config.json"
        if config_text is not None:
            cfg.write_text(config_text)
        env = dict(os.environ, CHATGPT_CONSULT_CONFIG=str(cfg))
        r = subprocess.run([sys.executable, "-c", PROBE], cwd=BIN, env=env,
                           capture_output=True, text=True)
    return r


class UserConfig(unittest.TestCase):
    def test_no_file_keeps_original_defaults(self):
        r = load(None)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        # Dispatch: the default ledger lives in the private overlay when there is one.
        self.assertTrue(got.pop("ledger").endswith("ledger/consults.jsonl"))
        self.assertEqual(got["title"], "Consult_Machinist")

    def test_settings_override_all_three(self):
        r = load(json.dumps({"ledger": "ledger/alice.jsonl", "chatgpt_project": "AliceConsult",
                             "thread_prefix": "SConsult_"}))
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got, {"ledger": str(REPO / "ledger" / "alice.jsonl"),
                               "project": "AliceConsult", "title": "SConsult_Machinist"})

    def test_absolute_ledger_path_is_kept(self):
        r = load(json.dumps({"ledger": "/tmp/elsewhere.jsonl"}))
        self.assertEqual(json.loads(r.stdout)["ledger"], "/tmp/elsewhere.jsonl")

    def test_unreadable_file_refuses_rather_than_using_defaults(self):
        # Control arm: a broken file must NOT quietly fall back to the other user's ledger.
        r = load("{not json")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unreadable", r.stderr)


if __name__ == "__main__":
    unittest.main()
