"""Tests for outcome recording, legacy-compatible findings, pending nags and stats. No network."""
import io
import json
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))
import consult  # noqa: E402
import outcomes  # noqa: E402


def c(cid, started="2026-10-01T10:00:00-0700", kind="code_review", trigger="risky_implementation",
      sent=True, reply=500, error=None):
    return {"consult_id": cid, "started": started, "kind": kind, "trigger": trigger,
            "sent": sent, "reply_chars": reply, "error": error}


def f(cid, **kw):
    r = {"type": "FINDING", "consult_id": cid, "correctness": "confirmed",
         "verification_method": "test", "disposition": "applied", "changed_action": "no"}
    r.update(kw)
    return r


class Ledger(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.old = consult.LEDGER
        consult.LEDGER = self.tmp / "l.jsonl"

    def tearDown(self):
        consult.LEDGER = self.old

    def seed(self, *rows):
        consult.LEDGER.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        old = sys.argv
        sys.argv = ["consult.py", *argv]
        try:
            with redirect_stdout(out), redirect_stderr(err):
                rc = consult.main()
        finally:
            sys.argv = old
        return rc, out.getvalue(), err.getvalue()


class TestNormalize(unittest.TestCase):
    def test_legacy_row_readable(self):
        n = outcomes.normalize_finding(f("a", changed_action="no"))
        self.assertTrue(n["applied"])          # disposition applied, despite changed_action no
        self.assertEqual(n["changed_plan"], "no")
        self.assertEqual(n["verified_by"], "test")

    def test_legacy_source_inspection_is_requester(self):
        n = outcomes.normalize_finding(f("a", verification_method="source_inspection"))
        self.assertEqual(n["verified_by"], "requester")

    def test_new_row(self):
        n = outcomes.normalize_finding(f("a", applied="none", changed_plan="yes",
                                         verified_by="independent_agent", disposition="deferred"))
        self.assertFalse(n["applied"])
        self.assertEqual(n["changed_plan"], "yes")
        self.assertEqual(n["verified_by"], "independent_agent")

    def test_new_row_with_hash_applied(self):
        self.assertTrue(outcomes.normalize_finding(f("a", applied="abc1234"))["applied"])


class TestStatus(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(outcomes.attempt_status(c("a")), "delivered")
        self.assertEqual(outcomes.attempt_status(c("a", sent=False, reply=None, error="x")), "errored")
        self.assertEqual(outcomes.attempt_status(c("a", error="submitted but unread")), "errored")
        self.assertEqual(outcomes.attempt_status(c("a", sent=False, error="draft_only")), "errored")


class TestPending(Ledger):
    NOW = "2026-10-16T12:00:00-0700"

    def test_pending_lists_old_delivered_without_outcome(self):
        rows = [c("old"), c("done"), {"type": "OUTCOME", "consult_id": "done"},
                c("err", sent=False, reply=None, error="boom"),
                c("pilot", trigger="pilot"),
                c("fresh", started="2026-10-16T08:00:00-0700")]
        p = outcomes.pending_outcomes(rows, hours=24, now=self.NOW)
        self.assertEqual([r["consult_id"] for r in p], ["old"])

    def test_command_text(self):
        self.assertIn("--record-outcome old", outcomes.record_command("old"))

    def test_cli_pending(self):
        self.seed(c("old"))
        rc, out, _ = self.run_main("--pending-outcomes")
        self.assertEqual(rc, 0)
        self.assertIn("--record-outcome old", out)

    def test_nag_capped(self):
        rows = [c(f"x{i}") for i in range(12)]
        lines = outcomes.nag_lines(rows, cap=5)
        self.assertEqual(len([l for l in lines if "--record-outcome" in l]), 5)
        self.assertTrue(any("7 more" in l for l in lines))


class TestRecordOutcome(Ledger):
    def args(self, **kw):
        a = dict(findings_total=None, findings_confirmed=None, false_positives=None, applied=None,
                 downstream_tokens=None, outcome_note="", no_findings=False)
        a.update(kw)
        return SimpleNamespace(**a)

    def outcome_rows(self):
        return [r for r in consult.read_ledger() if r.get("type") == "OUTCOME"]

    def test_derives_from_findings(self):
        self.seed(c("a"), f("a"), f("a", correctness="disconfirmed", disposition="rejected"))
        self.assertEqual(consult.record_outcome("a", self.args()), 0)
        o = self.outcome_rows()[0]
        self.assertEqual((o["findings_total"], o["findings_confirmed"], o["false_positives"],
                          o["applied"], o["escaped_later"]), (2, 1, 1, 1, 0))
        self.assertFalse(o["no_findings"])

    def test_no_findings_valid(self):
        self.seed(c("a"))
        self.assertEqual(consult.record_outcome("a", self.args(no_findings=True)), 0)
        o = self.outcome_rows()[0]
        self.assertTrue(o["no_findings"])
        self.assertEqual(o["findings_total"], 0)

    def test_no_findings_conflicts_with_findings(self):
        self.seed(c("a"), f("a"))
        self.assertEqual(consult.record_outcome("a", self.args(no_findings=True)), 2)

    def test_nothing_to_record_refused(self):
        self.seed(c("a"))
        self.assertEqual(consult.record_outcome("a", self.args()), 2)

    def test_unknown_consult(self):
        self.seed(c("a"))
        self.assertEqual(consult.record_outcome("zzz", self.args(no_findings=True)), 1)

    def test_downstream_tokens(self):
        self.seed(c("a"))
        consult.record_outcome("a", self.args(no_findings=True, downstream_tokens=7400000))
        self.assertEqual(self.outcome_rows()[0]["downstream_tokens"], 7400000)

    def test_errored_consult_refused(self):
        self.seed(c("e", sent=False, reply=None, error="boom"))
        self.assertEqual(consult.record_outcome("e", self.args(no_findings=True)), 1)

    def test_escape(self):
        self.seed(c("a"))
        self.assertEqual(consult.record_escape("a", "missed off-by-one"), 0)
        e = [r for r in consult.read_ledger() if r.get("type") == "ESCAPE"][0]
        self.assertEqual(e["consult_id"], "a")
        self.assertEqual(consult.record_escape("zzz", "x"), 1)


class TestFindingFields(Ledger):
    def ns(self, **kw):
        a = dict(finding_id="f1", novel="yes", correctness="confirmed", verification="test",
                 severity="major", disposition="applied", rejection_reason="", changed_action=None,
                 changed_plan="no", applied="abc1234", verified_by=None, fix_commit=None,
                 duplicate_of=None, note="")
        a.update(kw)
        return SimpleNamespace(**a)

    def test_new_fields_written(self):
        self.seed(c("a"))
        self.assertEqual(consult.record_finding("a", self.ns()), 0)
        r = consult.read_ledger()[-1]
        self.assertEqual(r["applied"], "abc1234")
        self.assertEqual(r["fix_commit"], "abc1234")
        self.assertEqual(r["changed_plan"], "no")
        self.assertEqual(r["verified_by"], "test")
        self.assertNotIn("changed_action", r)

    def test_verified_by_defaults_requester_for_source(self):
        self.seed(c("a"))
        consult.record_finding("a", self.ns(verification="source_inspection"))
        self.assertEqual(consult.read_ledger()[-1]["verified_by"], "requester")

    def test_legacy_changed_action_maps_to_plan(self):
        self.seed(c("a"))
        consult.record_finding("a", self.ns(changed_action="yes", changed_plan=None))
        self.assertEqual(consult.read_ledger()[-1]["changed_plan"], "yes")

    def test_applied_none_with_disposition_applied_refused(self):
        self.seed(c("a"))
        self.assertEqual(consult.record_finding("a", self.ns(applied="none")), 2)


class TestImport(Ledger):
    def test_jsonl_and_csv(self):
        self.seed(c("a"))
        p = self.tmp / "in.jsonl"
        p.write_text(json.dumps({"consult_id": "a", "finding_id": "x1", "correctness": "confirmed",
                                 "verification": "test", "severity": "major",
                                 "disposition": "applied", "applied": "deadbee",
                                 "note": "n"}) + "\n")
        q = self.tmp / "in.csv"
        q.write_text("consult_id,finding_id,correctness,verification,severity,disposition,applied\n"
                     "a,x2,disconfirmed,source_inspection,minor,rejected,none\n")
        for path in (p, q):
            rc, out, err = self.run_main("--import-findings", str(path))
            self.assertEqual(rc, 0, err)
        fs = [r for r in consult.read_ledger() if r.get("type") == "FINDING"]
        self.assertEqual(len(fs), 2)
        self.assertEqual(fs[1]["disposition"], "rejected")

    def test_bad_row_aborts_all(self):
        self.seed(c("a"))
        p = self.tmp / "in.jsonl"
        p.write_text(json.dumps({"consult_id": "a", "correctness": "confirmed",
                                 "verification": "none"}) + "\n")
        rc, _, _ = self.run_main("--import-findings", str(p))
        self.assertNotEqual(rc, 0)
        self.assertEqual([r for r in consult.read_ledger() if r.get("type") == "FINDING"], [])

class TestRecordGate(Ledger):
    def many(self, n, repo="r1"):
        return [dict(c(f"2026-09-{i + 1:02d}-x"), repo_id=repo, started=f"2026-09-{i + 1:02d}T10:00:00-0700")
                for i in range(n)]

    def test_gate_counts_only_this_repo_and_skips_recorded(self):
        rows = self.many(5) + self.many(3, "other")
        rows.append(f("2026-09-01-x"))
        lines, refuse = outcomes.record_gate(rows, "r1", limit=5)
        self.assertIn("4 earlier", lines[0])
        self.assertFalse(refuse)
        self.assertTrue(outcomes.record_gate(self.many(5), "r1", limit=5)[1])
        self.assertEqual(outcomes.record_gate(self.many(5), "none", limit=5), ([], False))

    def test_pending_lists_unrecorded(self):
        self.seed(*self.many(2, "zz"))
        rc, out, _ = self.run_main("--pending", "--all-repos")
        self.assertEqual(rc, 0)
        self.assertIn("2 delivered consult(s)", out)

    def test_skip_flag_and_exemptions_exist(self):
        rows = self.many(6, consult.repo_identity(consult.project_root()))
        self.seed(*rows)
        rc, _, err = self.run_main("--prompt", "hi", "--trigger", "other")
        self.assertEqual(rc, 4)
        self.assertIn("--skip-record-check", err)



class TestStats(Ledger):
    def test_stats_excludes_pilot_and_counts(self):
        self.seed(c("a"), f("a"), f("a", correctness="disconfirmed", disposition="rejected"),
                  {"type": "OUTCOME", "consult_id": "a", "findings_total": 2, "escaped_later": 0},
                  {"type": "ESCAPE", "consult_id": "a", "note": "x"},
                  c("b", kind="design_review"),
                  c("p", trigger="pilot"), f("p"),
                  c("e", sent=False, reply=None, error="boom"))
        rc, out, _ = self.run_main("--stats")
        self.assertEqual(rc, 0)
        self.assertNotIn("pilot", out)
        s = outcomes.stats(consult.read_ledger())
        cr = s["by_kind"]["code_review"]
        self.assertEqual((cr["delivered"], cr["with_outcome"], cr["confirmed"], cr["false_positives"],
                          cr["applied"], cr["escaped"], cr["errored"]), (1, 1, 1, 1, 1, 1, 1))
        self.assertEqual(s["by_kind"]["design_review"]["delivered"], 1)
        self.assertIn("risky_implementation", s["by_trigger"])
        self.assertNotIn("pilot", s["by_trigger"])


if __name__ == "__main__":
    unittest.main()
