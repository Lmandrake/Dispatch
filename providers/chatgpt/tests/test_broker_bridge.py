"""The broker speaks to the extension bridge's unix socket and opens no websocket of its own.

Offline: a fake bridge records every request. No Chrome, no ChatGPT.
"""
import json
import os
import pathlib
import socket
import sys
import tempfile
import threading
import unittest
from unittest import mock

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))
import broker as B  # noqa: E402
import cdp_client  # noqa: E402

TAB = {"targetId": "T1", "type": "page", "url": "https://chatgpt.com/c/abc", "attached": False}
EVIL = {"targetId": "T2", "type": "page", "url": "https://example.com/", "attached": False}


class FakeBridge:
    def __init__(self, path: str, session_cmd: bool):
        self.path, self.session_cmd, self.reqs = path, session_cmd, []
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(path)
        self.srv.listen(8)
        threading.Thread(target=self.loop, daemon=True).start()

    def answer(self, req):
        cmd = req.get("cmd")
        if cmd == "ping":
            return {"pong": True}
        if cmd == "status":
            return {"connected": True, "connecting": False}
        if cmd == "eval":
            return {"result": {"type": "string", "value": "https://chatgpt.com|complete"}}
        if cmd == "session":
            if not self.session_cmd:
                raise KeyError("unknown cmd: session")
            if req["method"] == "Runtime.evaluate":
                return {"result": {"type": "string", "value": "https://chatgpt.com|complete"}}
            return {}
        if cmd == "browser":
            m = req["method"]
            if m == "Target.getTargets":
                return {"targetInfos": [dict(TAB), dict(EVIL)]}
            if m == "Target.createTarget":
                return {"targetId": "T9"}
            if m == "Target.attachToTarget":
                assert req["params"]["flatten"] is False
                return {"sessionId": "NF-" + req["params"]["targetId"]}
            return {}
        raise KeyError("unknown cmd: " + str(cmd))

    def loop(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            fh = c.makefile("rwb")
            for line in fh:
                req = json.loads(line)
                self.reqs.append(req)
                try:
                    out = {"id": req.get("id"), "ok": True, "result": self.answer(req)}
                except KeyError as e:
                    out = {"id": req.get("id"), "ok": False, "error": e.args[0]}
                fh.write(json.dumps(out).encode() + b"\n")
                fh.flush()
            c.close()

    def close(self):
        self.srv.close()


class Base(unittest.TestCase):
    session_cmd = True

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="bb", dir="/tmp")
        sock = os.path.join(self.dir, "b.sock")
        self.fake = FakeBridge(sock, self.session_cmd)
        self.env = mock.patch.dict(os.environ, {"CDP_BRIDGE_SOCK": sock})
        self.env.start()
        # Any attempt to open a private websocket or spawn a presser fails the test.
        self.ws = mock.patch.object(cdp_client, "WS", side_effect=AssertionError("opened a websocket"))
        self.ws.start()
        mock.patch("subprocess.Popen", side_effect=AssertionError("spawned a process")).start()
        mock.patch("subprocess.run", side_effect=AssertionError("ran a process")).start()
        mock.patch.object(B, "BLIND_SETTLE_S", 0).start()
        self.broker = B.Broker(idle_exit=60)

    def tearDown(self):
        mock.patch.stopall()
        self.fake.close()

    def call(self, method, params=None, sid=None, client=1):
        return self.broker.cdp_call(method, params or {}, sid, None, client)

    def flow(self):
        """What CDPSession.reuse_page + compose + press_enter issue, through the broker."""
        targets = self.call("Target.getTargets")["targetInfos"]
        self.assertEqual({t["targetId"] for t in targets}, {"T1", "T2"})
        sid = self.call("Target.attachToTarget", {"targetId": "T1", "flatten": True})["sessionId"]
        self.call("Runtime.enable", sid=sid)
        self.call("Page.navigate", {"url": "https://chatgpt.com/c/abc"}, sid=sid)
        r = self.call("Runtime.evaluate", {"expression": "1", "returnByValue": True}, sid=sid)
        self.assertEqual(r["result"]["value"], "https://chatgpt.com|complete")
        self.call("Input.insertText", {"text": "hello\nworld"}, sid=sid)
        for kind in ("keyDown", "keyUp"):
            self.call("Input.dispatchKeyEvent", {"type": kind, "key": "Enter"}, sid=sid)
        return sid


class WithSessionCommand(Base):
    session_cmd = True

    def test_flow_uses_session_command(self):
        self.flow()
        cmds = [(r["cmd"], r.get("method")) for r in self.fake.reqs]
        self.assertIn(("session", "Input.insertText"), cmds)
        self.assertIn(("session", "Input.dispatchKeyEvent"), cmds)
        self.assertNotIn(("browser", "Target.sendMessageToTarget"), cmds)
        self.assertEqual(self.broker.connections, 1)

    def test_off_origin_attach_still_refused(self):
        with self.assertRaises(B.Refused):
            self.call("Target.attachToTarget", {"targetId": "T2", "flatten": True})

    def test_denied_and_unlisted_methods_never_reach_bridge(self):
        n = len(self.fake.reqs)
        for m in ("Target.activateTarget", "Page.bringToFront", "Target.sendMessageToTarget"):
            with self.assertRaises(B.Refused):
                self.call(m, {})
        # only the connect-time ping/status went out, nothing carrying the method
        self.assertFalse([r for r in self.fake.reqs[n:] if r.get("method") in
                          ("Target.activateTarget", "Page.bringToFront")])

    def test_foreign_session_refused(self):
        sid = self.call("Target.attachToTarget", {"targetId": "T1", "flatten": True})["sessionId"]
        with self.assertRaises(B.Refused):
            self.call("Input.insertText", {"text": "x"}, sid=sid, client=2)


class WithoutSessionCommand(Base):
    session_cmd = False

    def test_flow_falls_back_to_eval_and_blind_messages(self):
        self.flow()
        sends = [json.loads(r["params"]["message"]) for r in self.fake.reqs
                 if r.get("method") == "Target.sendMessageToTarget"]
        self.assertEqual([m["method"] for m in sends],
                         ["Page.navigate", "Input.insertText",
                          "Input.dispatchKeyEvent", "Input.dispatchKeyEvent"])
        self.assertEqual(sends[1]["params"]["text"], "hello\nworld")
        evals = [r for r in self.fake.reqs if r["cmd"] == "eval"]
        self.assertTrue(evals and all(r["targetId"] == "T1" for r in evals))
        # one non-flattened attach per target, reused
        attaches = [r for r in self.fake.reqs if r.get("method") == "Target.attachToTarget"]
        self.assertEqual(len(attaches), 1)


class ExtShapedBridge(Base):
    """The extension bridge: `session` exists, and browser-level methods beyond the Target trio
    are refused. The consult flow must never need one."""
    session_cmd = True

    def setUp(self):
        super().setUp()
        orig = self.fake.answer

        def answer(req):
            if req.get("cmd") == "browser" and req["method"] not in (
                    "Target.getTargets", "Target.createTarget", "Target.closeTarget"):
                raise KeyError(f"browser {req['method']} is not available over the extension transport")
            return orig(req)
        self.fake.answer = answer

    def test_flow_needs_no_other_browser_method(self):
        self.flow()
        tid = self.call("Target.createTarget", {"url": "https://chatgpt.com/", "background": True})["targetId"]
        self.call("Target.closeTarget", {"targetId": tid})
        browser = {r["method"] for r in self.fake.reqs if r["cmd"] == "browser"}
        self.assertLessEqual(browser, {"Target.getTargets", "Target.createTarget", "Target.closeTarget"})


class SocketSelection(unittest.TestCase):
    def env(self, **kv):
        base = {"CDP_BRIDGE_SOCK": "", "CDP_TRANSPORT": ""}
        return mock.patch.dict(os.environ, {**base, **kv})

    def test_default_is_the_extension_bridge(self):
        with self.env():
            self.assertEqual(B.bridge_sock().name, "chrome-ext-bridge.sock")

    def test_ws_is_opt_in(self):
        with self.env(CDP_TRANSPORT="ws"):
            self.assertEqual(B.bridge_sock().name, "cdp-bridge.sock")

    def test_explicit_socket_wins_and_bad_transport_refused(self):
        with self.env(CDP_BRIDGE_SOCK="/tmp/x.sock"):
            self.assertEqual(str(B.bridge_sock()), "/tmp/x.sock")
        with self.env(CDP_TRANSPORT="auto"), self.assertRaises(cdp_client.CDPError):
            B.bridge_sock()

    def test_connect_runs_tools_cdp_on_the_same_transport(self):
        seen = {}

        def run(argv, **kw):
            seen.update(kw["env"])
            return mock.Mock(returncode=0, stdout="", stderr="")
        with self.env(MACHINIST_TOOLS=str(BIN)), \
             mock.patch.object(B.BridgeCDP, "alive", return_value=False), \
             mock.patch.object(B.BridgeCDP, "connected", return_value=True), \
             mock.patch.object(B.shutil, "which", return_value="/usr/bin/node"), \
             mock.patch.object(pathlib.Path, "exists", return_value=True), \
             mock.patch("subprocess.run", side_effect=run):
            B.BridgeCDP().connect()
        self.assertEqual(seen["CDP_TRANSPORT"], "ext")
        self.assertTrue(seen["CDP_BRIDGE_SOCK"].endswith("chrome-ext-bridge.sock"))


class BridgeDown(unittest.TestCase):
    def test_unreachable_bridge_is_a_cdp_error_not_a_private_socket(self):
        with mock.patch.dict(os.environ, {"CDP_BRIDGE_SOCK": "/tmp/nonexistent-bridge.sock",
                                          "MACHINIST_TOOLS": "/nonexistent"}), \
             mock.patch.object(cdp_client, "WS", side_effect=AssertionError("opened a websocket")), \
             mock.patch("subprocess.run", side_effect=AssertionError("ran a process")) as run:
            # MACHINIST_TOOLS points nowhere, so connect must refuse before running anything.
            with self.assertRaises(cdp_client.CDPError):
                B.Broker(idle_exit=60).cdp_call("Target.getTargets", {}, None, None, 1)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
