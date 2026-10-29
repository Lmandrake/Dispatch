"""Tests for the codex transport. No Docker, no network, no Chrome: the container call is mocked.

Run: python3 -m unittest discover -s providers/chatgpt/tests
"""
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))
import codex_worker as cw  # noqa: E402
import consult  # noqa: E402


def events(*evs):
    return "\n".join(json.dumps(e) for e in evs) + "\n"


OK_STREAM = events(
    {"type": "thread.started", "thread_id": "th_123"},
    {"type": "item.completed", "item": {"id": "i0", "type": "error",
                                        "message": "Falling back from WebSockets to HTTPS"}},
    {"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": "the answer"}},
    {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 3}})


def failed(msg):
    return events({"type": "thread.started", "thread_id": "th_9"},
                  {"type": "error", "message": "Reconnecting... 1/5"},
                  {"type": "turn.failed", "error": {"message": msg}})


class FakeRunner:
    def __init__(self, stdout="", rc=0, raise_timeout=False):
        self.calls, self.stdout, self.rc, self.raise_timeout = [], stdout, rc, raise_timeout

    def __call__(self, argv, input=None, **kw):
        self.calls.append((argv, input))
        if self.raise_timeout:
            raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
        return subprocess.CompletedProcess(argv, self.rc, self.stdout, "")


class Sandbox(unittest.TestCase):
    """Every test gets its own codex home, packet root and ledger."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.home = self.tmp / "codex-home"
        self.home.mkdir(mode=0o700)
        (self.home / "auth.json").write_text("{}")
        self.rhome = self.tmp / "research-home"
        self.rhome.mkdir(mode=0o700)
        (self.rhome / "auth.json").write_text('{"research": true}')
        for target, val in ((cw, {"CODEX_HOME": self.home, "RESEARCH_HOME": self.rhome,
                                  "PACKET_ROOT": self.tmp / "packets"}),
                            (consult, {"LEDGER": self.tmp / "ledger.jsonl"})):
            for k, v in val.items():
                p = mock.patch.object(target, k, v)
                p.start()
                self.addCleanup(p.stop)

    def tearDown(self):
        subprocess.run(["chmod", "-R", "u+rwx", str(self.tmp)])
        subprocess.run(["rm", "-rf", str(self.tmp)])


class ClassifyTests(unittest.TestCase):
    def test_completed(self):
        r = cw.classify(cw.parse_events(OK_STREAM), 0)
        self.assertEqual((r.outcome, r.answer, r.thread_id), (cw.COMPLETED, "the answer", "th_123"))

    def test_auth(self):
        r = cw.classify(cw.parse_events(failed("unexpected status 401 Unauthorized: Missing bearer")), 1)
        self.assertEqual(r.outcome, cw.AUTH_REQUIRED)

    def test_allowance(self):
        r = cw.classify(cw.parse_events(failed("You've hit your usage limit. Try again later.")), 1)
        self.assertEqual(r.outcome, cw.ALLOWANCE_EXHAUSTED)

    def test_transport(self):
        r = cw.classify(cw.parse_events(failed("stream disconnected before completion")), 1)
        self.assertEqual(r.outcome, cw.TRANSPORT_ERROR)

    def test_empty_answer_is_not_success(self):
        r = cw.classify(cw.parse_events(events({"type": "turn.completed"})), 0)
        self.assertNotEqual(r.outcome, cw.COMPLETED)

    def test_exit_codes_distinct(self):
        self.assertEqual(len(set(cw.EXIT_CODES.values())), len(cw.EXIT_CODES))


class PacketTests(Sandbox):
    def test_packet_holds_only_prompt_and_attachments(self):
        att = self.tmp / "evidence.py"
        att.write_text("x = 1\n")
        (self.tmp / "not_attached.txt").write_text("CANARY")
        pdir, text, digest = cw.build_packet("question", [att], self.tmp / "packets")
        files = sorted(str(p.relative_to(pdir)) for p in pdir.rglob("*") if p.is_file())
        self.assertEqual(files, ["attachments/00-evidence.py", "prompt.md"])
        self.assertIn("x = 1", text)
        self.assertNotIn("CANARY", text)
        self.assertEqual(len(digest), 64)

    def test_secret_in_attachment_refused_before_docker(self):
        att = self.tmp / "cfg.txt"
        att.write_text("api_key = " + "9f3a7c2e" + "8b1d4f6a0c5e9b2d\n")  # a value, not a name; split for gitleaks
        runner = FakeRunner(OK_STREAM)
        r = cw.run("clean prompt", [att], runner=runner)
        self.assertEqual(r.outcome, cw.REFUSED)
        self.assertEqual(runner.calls, [])

    def test_binary_attachment_refused(self):
        att = self.tmp / "b.bin"
        att.write_bytes(b"\xff\xfe\x00")
        r = cw.run("q", [att], runner=FakeRunner(OK_STREAM))
        self.assertEqual(r.outcome, cw.REFUSED)


class ContainerTests(Sandbox):
    def test_docker_args_boundary(self):
        a = cw.docker_args(pathlib.Path("/x/packet"), "n", None)
        mounts = [a[i + 1] for i, v in enumerate(a) if v == "-v"]
        self.assertEqual(mounts, [f"{self.home}:/codex", "/x/packet:/packet:ro"])
        for flag in ("--read-only", "--rm"):
            self.assertIn(flag, a)
        self.assertEqual(a[a.index("--cap-drop") + 1], "ALL")
        self.assertEqual(a[a.index("--security-opt") + 1], "no-new-privileges")
        self.assertNotIn("docker.sock", " ".join(a))
        self.assertNotIn(str(pathlib.Path.home()) + ":", " ".join(mounts))
        self.assertIn("--ephemeral", a)
        self.assertIn("--json", a)
        self.assertEqual(a[a.index("--sandbox") + 1], "read-only")
        self.assertNotIn("app", a[a.index(cw.IMAGE):])

    def test_prompt_goes_on_stdin_with_attachments_inlined(self):
        att = self.tmp / "e.txt"
        att.write_text("EVIDENCE")
        runner = FakeRunner(OK_STREAM)
        r = cw.run("Q?", [att], runner=runner)
        self.assertEqual(r.outcome, cw.COMPLETED)
        self.assertIn("EVIDENCE", runner.calls[0][1])
        self.assertTrue(r.packet_sha256)

    def test_no_auth_file_is_auth_required_without_running(self):
        (self.home / "auth.json").unlink()
        runner = FakeRunner(OK_STREAM)
        self.assertEqual(cw.run("q", runner=runner).outcome, cw.AUTH_REQUIRED)
        self.assertEqual(runner.calls, [])

    def test_timeout_is_deadline(self):
        with mock.patch.object(cw.subprocess, "run") as kill:
            r = cw.run("q", runner=FakeRunner(raise_timeout=True))
        self.assertEqual(r.outcome, cw.DEADLINE)
        self.assertEqual(kill.call_args[0][0][-2], "kill")

    def test_config_reinstalled_and_auth_untouched(self):
        (self.home / "auth.json").write_text('{"fresh": true}')
        cw.run("q", runner=FakeRunner(OK_STREAM))
        self.assertEqual((self.home / "auth.json").read_text(), '{"fresh": true}')
        self.assertEqual((self.home / "config.toml").read_text(), cw.REPO_CONFIG.read_text())

    def test_lock_serializes(self):
        order = []

        def slow(argv, input=None, **kw):
            order.append("start")
            time.sleep(0.6)
            order.append("end")
            return subprocess.CompletedProcess(argv, 0, OK_STREAM, "")
        ts = [threading.Thread(target=cw.run, args=("q",), kwargs={"runner": slow}) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(order, ["start", "end", "start", "end"])


class ConsultIntegration(Sandbox):
    def setUp(self):
        super().setUp()
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.cwd = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, self.cwd)
        p = mock.patch.object(consult, "open_transport",
                              side_effect=AssertionError("codex route touched Chrome"))
        p.start()
        self.addCleanup(p.stop)
        # The sandbox provisions the profile homes; docker itself is the host's business.
        # Without this the default-route tests pass only on a machine with docker on PATH.
        real_which = shutil.which
        w = mock.patch("shutil.which",
                       side_effect=lambda c, *a, **k: "/usr/bin/docker" if c == "docker"
                       else real_which(c, *a, **k))
        w.start()
        self.addCleanup(w.stop)

    def main(self, *argv, runner=None):
        runner = runner or FakeRunner(OK_STREAM)
        real = cw.run
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(cw, "run", lambda *a, **k: real(*a, runner=runner, **k)), \
                mock.patch.object(sys, "argv", ["consult.py", *argv]), \
                redirect_stdout(out), redirect_stderr(err):
            rc = consult.main()
        return rc, out.getvalue(), err.getvalue(), runner

    def ledger(self):
        lp = consult.LEDGER
        return [json.loads(x) for x in lp.read_text().splitlines()] if lp.exists() else []

    def test_unenrolled_is_draft_and_sends_nothing(self):
        rc, _, err, runner = self.main("--transport", "codex", "--prompt", "hi")
        self.assertEqual(rc, 0)
        self.assertEqual(runner.calls, [])
        self.assertIn("draft", err)

    def test_enrolled_sends_records_ledger_and_transcript(self):
        consult.enroll(pathlib.Path(self.repo))
        rc, out, _, _ = self.main("--transport", "codex", "--prompt", "hi", "--kind", "other",
                                  "--trigger", "user_asked", "--believe", "I think X")
        self.assertEqual(rc, 0)
        self.assertIn("the answer", out)
        row = self.ledger()[-1]
        self.assertEqual((row["transport"], row["sent"], row["thread_url"], row["codex_outcome"]),
                         ("codex", True, "codex:th_123", "completed"))
        self.assertEqual(row["belief_snapshot"], "I think X")
        self.assertTrue(row["packet_sha256"])
        self.assertIn("the answer", (self.repo / ".consult" / "transcript.md").read_text())

    def test_secret_refused_on_codex(self):
        consult.enroll(pathlib.Path(self.repo))
        rc, _, _, runner = self.main("--transport", "codex", "--prompt", "password = " + "hunter2hunter2")
        self.assertEqual(rc, 2)
        self.assertEqual(runner.calls, [])

    def test_idempotent(self):
        consult.enroll(pathlib.Path(self.repo))
        self.main("--transport", "codex", "--prompt", "same")
        rc, _, err, runner = self.main("--transport", "codex", "--prompt", "same")
        self.assertEqual(rc, 0)
        self.assertEqual(runner.calls, [])
        self.assertIn("already consulted", err)

    def test_failure_has_distinct_code_and_no_chrome_fallback(self):
        consult.enroll(pathlib.Path(self.repo))
        for msg, code in (("401 Unauthorized", 20), ("usage limit reached", 21),
                          ("connection reset", 22)):
            rc, _, err, _ = self.main("--transport", "codex", "--prompt", f"q {code}",
                                      runner=FakeRunner(failed(msg), rc=1))
            self.assertEqual(rc, code, msg)
            self.assertIn("Not falling back to Chrome", err)
            row = self.ledger()[-1]
            self.assertFalse(row["sent"])
            self.assertTrue(row["error"].startswith(row["codex_outcome"]))


class ProfileTests(Sandbox):
    """Research profile (standing ruling 2026-10-07): separate login, web search, never the review home."""

    def mounts(self, a):
        return [a[i + 1] for i, v in enumerate(a) if v == "-v"]

    def test_homes_never_cross(self):
        rev = self.mounts(cw.docker_args(pathlib.Path("/x/p"), "n", None, cw.REVIEW))
        res = self.mounts(cw.docker_args(pathlib.Path("/x/p"), "n", None, cw.RESEARCH))
        self.assertEqual(rev, [f"{self.home}:/codex", "/x/p:/packet:ro"])
        self.assertEqual(res, [f"{self.rhome}:/codex", "/x/p:/packet:ro"])
        self.assertFalse(any(str(self.home) in m for m in res))
        self.assertFalse(any(str(self.rhome) in m for m in rev))

    def test_same_home_refused(self):
        with mock.patch.object(cw, "RESEARCH_HOME", self.home):
            with self.assertRaises(ValueError):
                cw.docker_args(pathlib.Path("/x/p"), "n", None, cw.RESEARCH)
            self.assertEqual(cw.run("q", runner=FakeRunner(OK_STREAM), profile=cw.RESEARCH).outcome,
                             cw.REFUSED)

    def test_search_only_on_research_and_top_level(self):
        rev = cw.docker_args(pathlib.Path("/x/p"), "n", None, cw.REVIEW)
        res = cw.docker_args(pathlib.Path("/x/p"), "n", None, cw.RESEARCH)
        self.assertNotIn("--search", rev)
        self.assertEqual(res.index("--search"), res.index(cw.IMAGE) + 1)
        self.assertLess(res.index("--search"), res.index("exec"))
        # Same hardening on both.
        strip = lambda a: [v for v in a if v != "--search" and ":/codex" not in v]
        self.assertEqual(strip(rev), strip(res))

    def test_research_config_differs_only_in_web_and_code_mode(self):
        def body(p):
            return [ln for ln in p.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
        rev, res = body(cw.REPO_CONFIG), body(cw.RESEARCH_CONFIG)
        diff = sorted((set(rev) ^ set(res)))
        self.assertEqual(len(rev), len(res))
        self.assertEqual([d.split("#")[0].strip() for d in diff],
                         ['code_mode_host = false', 'code_mode_host = true',
                          'web_search = "disabled"', 'web_search = "live"'])
        for line in ('enabled = false', 'persistence = "none"', 'exporter = "none"',
                     'shell_tool = false', 'multi_agent = false'):
            self.assertIn(line, res)

    def test_config_installed_per_profile(self):
        cw.run("q", runner=FakeRunner(OK_STREAM), profile=cw.RESEARCH)
        self.assertEqual((self.rhome / "config.toml").read_text(), cw.RESEARCH_CONFIG.read_text())
        self.assertFalse((self.home / "config.toml").exists())
        self.assertEqual((self.rhome / "auth.json").read_text(), '{"research": true}')
        self.assertTrue((self.rhome / ".worker.lock").exists())
        self.assertFalse((self.home / ".worker.lock").exists())
        cw.run("q2", runner=FakeRunner(OK_STREAM))
        self.assertEqual((self.home / "config.toml").read_text(), cw.REPO_CONFIG.read_text())

    def test_research_without_auth_is_auth_required_naming_login(self):
        (self.rhome / "auth.json").unlink()
        runner = FakeRunner(OK_STREAM)
        r = cw.run("q", runner=runner, profile=cw.RESEARCH)
        self.assertEqual(r.outcome, cw.AUTH_REQUIRED)
        self.assertEqual(runner.calls, [])
        self.assertIn("login --device-auth", r.message)
        self.assertIn(str(self.rhome), r.message)
        self.assertNotIn(str(self.home) + ":", r.message)

    def test_lock_is_per_profile(self):
        order = []

        def slow(argv, input=None, **kw):
            order.append("start")
            time.sleep(0.6)
            order.append("end")
            return subprocess.CompletedProcess(argv, 0, OK_STREAM, "")
        ts = [threading.Thread(target=cw.run, args=("q",), kwargs={"runner": slow, "profile": p})
              for p in (cw.REVIEW, cw.RESEARCH)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(order[:2], ["start", "start"])


class ResearchRouting(ConsultIntegration):
    def test_research_kind_defaults_to_codex_research(self):
        consult.enroll(pathlib.Path(self.repo))
        for argv in (("--kind", "literature_review"), ("--trigger", "research_needed")):
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("CONSULT_TRANSPORT", None)
                rc, out, _, runner = self.main("--prompt", f"newest python {argv}", *argv)
            self.assertEqual(rc, 0)
            a = runner.calls[0][0]
            self.assertIn("--search", a)
            self.assertIn(f"{self.rhome}:/codex", a)
            row = self.ledger()[-1]
            self.assertEqual((row["transport"], row["codex_profile"]), ("codex", "research"))

    def test_review_default_is_web_enabled_research_profile(self):
        consult.enroll(pathlib.Path(self.repo))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CONSULT_TRANSPORT", None)
            rc, _, _, runner = self.main("--prompt", "review this", "--kind", "code_review")
        self.assertEqual(rc, 0)
        self.assertIn("--search", runner.calls[0][0])
        self.assertIn(f"{self.rhome}:/codex", runner.calls[0][0])
        self.assertEqual(self.ledger()[-1]["codex_profile"], "research")

    def test_no_web_selects_locked_review_profile(self):
        consult.enroll(pathlib.Path(self.repo))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CONSULT_TRANSPORT", None)
            rc, _, _, runner = self.main("--prompt", "review this", "--kind", "other", "--no-web")
        self.assertEqual(rc, 0)
        self.assertNotIn("--search", runner.calls[0][0])
        self.assertIn(f"{self.home}:/codex", runner.calls[0][0])
        self.assertEqual(self.ledger()[-1]["codex_profile"], "review")

    def test_research_no_auth_exit_20_no_chrome(self):
        consult.enroll(pathlib.Path(self.repo))
        (self.rhome / "auth.json").unlink()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CONSULT_TRANSPORT", None)
            rc, _, err, runner = self.main("--prompt", "q", "--kind", "literature_review")
        self.assertEqual(rc, 20)
        self.assertEqual(runner.calls, [])
        self.assertIn("login --device-auth", err)
        self.assertIn("Not falling back to Chrome", err)


if __name__ == "__main__":
    unittest.main()



class ProvisioningDefault(unittest.TestCase):
    def test_provisioned_check_needs_docker_and_home(self):
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(cw, "home_for", return_value=pathlib.Path(d)), \
             mock.patch("shutil.which", return_value="/usr/bin/docker"):
            self.assertTrue(consult.codex_provisioned("research"))
        with mock.patch.object(cw, "home_for", return_value=pathlib.Path("/nonexistent/x")), \
             mock.patch("shutil.which", return_value="/usr/bin/docker"):
            self.assertFalse(consult.codex_provisioned("research"))
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(cw, "home_for", return_value=pathlib.Path(d)), \
             mock.patch("shutil.which", return_value=None):
            self.assertFalse(consult.codex_provisioned("research"))
