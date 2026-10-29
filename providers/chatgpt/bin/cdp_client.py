"""Minimal CDP-over-WebSocket client, stdlib only.

Chrome 144+ enables remote debugging at runtime and exposes ONLY the websocket named in
`<profile>/DevToolsActivePort`. All four `/json*` HTTP endpoints return 404 (verified
2026-09-26), so `--browserUrl`-style discovery cannot work and neither can any HTTP-based CDP
client. Hence this: a hand-rolled websocket good enough for Runtime.evaluate, with no new
dependency in the project venv.

Deliberately NOT a general websocket implementation. It speaks exactly the subset CDP needs:
masked client text frames, reassembled server frames, ping/pong, and id-routed responses.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import struct
import subprocess
import threading
from pathlib import Path

CHROME_PROFILE = Path(os.environ.get("CHATGPT_CHROME_PROFILE") or Path.home() / "Library/Application Support/Google/Chrome")


class CDPError(RuntimeError):
    pass


def read_debug_endpoint(profile: Path = CHROME_PROFILE) -> tuple[int, str]:
    """Port and browser ws path from DevToolsActivePort. Raises with a remedy, never guesses."""
    f = profile / "DevToolsActivePort"
    if not f.exists():
        raise CDPError(
            f"No DevToolsActivePort at {f}. Chrome is not serving remote debugging. "
            "Enable it at chrome://inspect/#remote-debugging, then retry."
        )
    parts = f.read_text().strip().split("\n")
    if len(parts) < 2:
        raise CDPError(f"DevToolsActivePort malformed: {parts!r}")
    return int(parts[0]), parts[1]


class WS:
    """Just enough RFC6455 for CDP."""

    def __init__(self, host: str, port: int, path: str, timeout: float = 120.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise CDPError("socket closed during websocket handshake")
            buf += chunk
        if b" 101 " not in buf.split(b"\r\n", 1)[0]:
            raise CDPError(f"handshake refused: {buf.split(chr(13).encode())[0]!r}")
        self._rest = buf.split(b"\r\n\r\n", 1)[1]
        self._lock = threading.Lock()

    def _recv_exact(self, n: int) -> bytes:
        out = self._rest[:n]
        self._rest = self._rest[n:]
        while len(out) < n:
            chunk = self.sock.recv(min(65536, n - len(out)))
            if not chunk:
                raise CDPError("socket closed mid-frame")
            out += chunk
        return out

    def send_text(self, s: str) -> None:
        payload = s.encode()
        header = bytearray([0x81])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        with self._lock:
            self.sock.sendall(bytes(header) + masked)

    def recv_text(self) -> str:
        """Reassemble one complete text message, handling fragments and control frames."""
        chunks: list[bytes] = []
        while True:
            b0, b1 = self._recv_exact(2)
            fin, opcode = b0 & 0x80, b0 & 0x0F
            length = b1 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv_exact(8))[0]
            if b1 & 0x80:  # server frames must not be masked, but tolerate it
                mask = self._recv_exact(4)
                data = bytes(c ^ mask[i % 4]
                             for i, c in enumerate(self._recv_exact(length)))
            else:
                data = self._recv_exact(length)
            if opcode == 0x9:           # ping -> pong
                with self._lock:
                    self.sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                continue
            if opcode == 0xA:           # pong
                continue
            if opcode == 0x8:
                raise CDPError("websocket closed by peer")
            chunks.append(data)
            if fin:
                return b"".join(chunks).decode("utf-8", "replace")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


CHROME_BUNDLE = "com.google.Chrome"


def frontmost_app() -> tuple[str, str] | None:
    """(bundle id, name) of the frontmost macOS app, or None if it cannot be read.

    The bundle id is the identity that matters — app names are neither unique nor stable, and the
    restore below acts on whatever this returns.
    """
    try:
        r = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to tell (first application process whose '
             'frontmost is true) to return (bundle identifier) & "|" & name'],
            capture_output=True, text=True, timeout=5)
        out = r.stdout.strip()
        if "|" not in out:
            return None
        bundle, _, name = out.partition("|")
        return (bundle.strip(), name.strip()) if bundle.strip() else None
    except Exception:
        return None


def activate_app(bundle_id: str) -> None:
    try:
        subprocess.run(["osascript", "-e", f'tell application id "{bundle_id}" to activate'],
                       capture_output=True, timeout=5)
    except Exception:
        pass


class CDPSession:
    """The CDP operations this tool needs, independent of how the bytes reach Chrome.

    Two transports implement `call`: `CDP`, which owns a websocket and therefore costs one approval
    sheet per instance, and `BrokerClient`, which borrows a shared broker's connection and costs
    none. Everything above `call` lives here precisely so the broker is a **transport swap** rather
    than a second implementation of the flow — two copies of the tab-reuse and origin-waiting rules
    would drift, and the rules are the expensive part.
    """

    target_id: str | None = None

    def call(self, method: str, params: dict | None = None,
             session_id: str | None = None) -> dict:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def reuse_page(self, url: str, match: str) -> str | None:
        """Attach to a tab already on `match` and navigate it to `url`. None if there is none.

        Why this exists. `open_page` created a tab on every call while `close()` deliberately leaves
        the tab open, so a session that retried a few times leaked **19 tabs** into the user's
        browser — and that pile of live ChatGPT tabs, each polling, rate-limited the very API the
        tool depends on: `/backend-api/conversations` started answering 429 and the tool could no
        longer find its own thread. Tab reuse is therefore not tidiness, it is what keeps the channel
        working.

        `match` is a substring the CALLER chooses, so reuse stays scoped to tabs already dedicated to
        this purpose. Navigating a tab the user is actively reading would be worse than opening one,
        so match on something specific, and let tab creation remain the fallback.
        """
        import time
        candidates = [t for t in self.call("Target.getTargets")["targetInfos"]
                      if t.get("type") == "page" and match in (t.get("url") or "")]
        # Prefer a tab nobody ELSE is driving. A target attached by a foreign debugger — a DevTools
        # window, another CDP client — was measured to hang: the attach returned in 0.0s and the
        # following `Runtime.enable` never answered, timing out at the full 120s socket deadline and
        # reading as a dead browser.
        #
        # `attached` alone is the wrong test, because the broker's own attachments set it too, and
        # skipping those would create a fresh tab on every consult — the 19-leaked-tabs failure this
        # method exists to prevent. The broker therefore annotates `brokerOwned`, and a tab we own is
        # still reusable. Without a broker the annotation is absent and `attached` is the right test,
        # since a private connection has attached nothing when it calls this.
        def foreign(t: dict) -> bool:
            return bool(t.get("attached")) and not t.get("brokerOwned")

        candidates.sort(key=foreign)
        for t in candidates:
            if foreign(t):
                continue
            # Try the next candidate rather than failing the consult. Chrome can report a tab as
            # unattached while a dying connection's session is still being torn down, and attaching to
            # one of those was measured to hang `Runtime.enable` until the socket deadline. One bad
            # candidate should cost a retry, not a consult — and `open_page` still falls back to
            # creating a tab if every candidate turns out to be unusable.
            try:
                session_id = self.call("Target.attachToTarget",
                                       {"targetId": t["targetId"], "flatten": True})["sessionId"]
                self.call("Runtime.enable", session_id=session_id)
                self.target_id = t["targetId"]
                if (t.get("url") or "").rstrip("/") != url.rstrip("/"):
                    self.call("Page.navigate", {"url": url}, session_id=session_id)
                    time.sleep(0.6)
                self.await_origin(session_id, url)
                return session_id
            except CDPError:
                continue
        return None

    def open_page(self, url: str, reuse_match: str | None = None) -> str:
        """Attach to a reusable tab when `reuse_match` finds one, else create our own.

        Target.createTarget returns before navigation commits, so a relative fetch issued
        immediately fails with "Failed to parse URL" against about:blank. Waiting for the
        origin is therefore part of opening, not an optional extra.

        `background: true` keeps the new tab from becoming the active tab — measured in a same-run
        A/B on 2026-09-26: with the flag the user's active tab was untouched, without it the probe
        tab took over. This is also the documented behaviour; the docs' only caveat is "not
        supported by headless shell". (An earlier comment here claimed the docs said "not supported
        for MacOS" and that we were trusting a measurement over the spec. That was a misreading,
        caught by a second-model review and corrected by reading the protocol page.)

        The control in `tools/focus_probe.py` stays regardless, because UI semantics regress and a
        silent regression here is invisible to everything else the tool checks.
        """
        if reuse_match:
            session_id = self.reuse_page(url, reuse_match)
            if session_id:
                return session_id
        target_id = self.call(
            "Target.createTarget", {"url": url, "background": True})["targetId"]
        session_id = self.call("Target.attachToTarget",
                               {"targetId": target_id, "flatten": True})["sessionId"]
        self.call("Runtime.enable", session_id=session_id)
        self.target_id = target_id
        self.await_origin(session_id, url)
        return session_id

    def await_origin(self, session_id: str, url: str, tries: int = 60) -> str:
        """Block until the tab is actually on the target origin and the DOM is usable."""
        import time
        from urllib.parse import urlparse
        want = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        state = None
        for _ in range(tries):
            # A tab MID-NAVIGATION reports an empty URL, and the broker re-checks a session's origin
            # on every call — so evaluating in that window is refused. That refusal is a transient
            # state of the very navigation this method is waiting for, and treating it as fatal made
            # `reuse_page` discard a perfectly good tab and open another, which is the tab-leak this
            # whole reuse path exists to prevent. Keep polling; the loop's own exhaustion is the real
            # failure, and the last error is carried into it.
            try:
                state = self.evaluate(
                    session_id, "[location.origin, document.readyState].join('|')",
                    await_promise=False)
            except CDPError as e:
                state = f"<not evaluable: {e}>"
                time.sleep(0.5)
                continue
            if state and state.startswith(want) and not state.endswith("loading"):
                return state
            time.sleep(0.5)
        raise CDPError(f"tab never reached {want} (last state: {state!r})")

    def evaluate(self, session_id: str, expression: str, await_promise: bool = True):
        r = self.call("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": await_promise,
            "returnByValue": True,
        }, session_id=session_id)
        if "exceptionDetails" in r:
            raise CDPError(f"JS threw: {r['exceptionDetails'].get('text')} "
                           f"{r['exceptionDetails'].get('exception', {}).get('description', '')}")
        return r.get("result", {}).get("value")

    def close_page(self) -> None:
        if getattr(self, "target_id", None):
            try:
                self.call("Target.closeTarget", {"targetId": self.target_id})
            except CDPError:
                pass


class CDP(CDPSession):
    """Id-routed CDP session over its own websocket.

    Connecting steals focus, and it is the ONLY step that does. Measured 2026-09-26 over six
    rounds: the websocket connect raises Chrome to frontmost every time — once per connection,
    not once per session — because Chrome activates itself to show the "Allow remote debugging?"
    sheet. Attach, navigate, insertText, a trusted Enter and closeTarget were each measured and
    steal nothing, and nothing re-steals while a connection sits idle.

    So the app the user was in is captured before the socket opens and restored after, turning a
    steal into a ~1s flicker. `restore_focus=False` opts out when the caller is already frontmost
    or wants the focus left alone.

    Restoration is **compare-and-restore, not unconditional**: it fires only when the app that is
    frontmost afterwards is Chrome itself. If anything else is frontmost, the user acted during
    that second and yanking the user back would be worse than the steal it repairs.

    Chromium's own source says this cannot be avoided on the user's normal profile. The runtime toggle at
    chrome://inspect starts the server in `kWithApprovalOnly`, which requires approval per incoming
    connection, and the dialog code calls `Activate()` on the browser window before showing the
    sheet. `--remote-debugging-port` does start in the no-approval mode, but since Chrome 136 that
    switch is ignored unless Chrome runs on a non-default `--user-data-dir` — which would mean a
    different profile and not the logged-in session. So the flicker is the price of using your own
    browser; the way to pay it less often is fewer connections, not a cleverer restore.
    """

    def __init__(self, timeout: float = 120.0, restore_focus: bool = True,
                 press_consent: bool = True):
        """Open the connection, pressing Chrome's approval sheet ourselves.

        Pressing that sheet belongs HERE, to the code that opens the socket, rather than to every
        caller. Chrome raises it on each connection, and an unanswered sheet does not error — the
        websocket handshake BLOCKS in `recv` until the deadline. So a caller who forgets the presser
        does not get a clear failure; it gets a 120 s hang that looks like a dead browser, and leaves
        a modal sitting on the user's screen for the user to find. That happened twice in one session,
        once via `--direct` and once from a probe, which is what moved this inside.
        """
        was = frontmost_app() if restore_focus else None
        port, path = read_debug_endpoint()
        presser = None
        if press_consent:
            try:
                presser = subprocess.Popen(
                    [str(Path(__file__).resolve().parent / "keep-allowing.sh"), "60"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL)
            except OSError:
                pass                      # no presser is survivable; a blocked handshake says so
        try:
            self.ws = WS("127.0.0.1", port, path, timeout=timeout)
        finally:
            if presser is not None:
                presser.terminate()
        self._id = 0
        if was and was[0] != CHROME_BUNDLE:
            now = frontmost_app()
            if now and now[0] == CHROME_BUNDLE:
                activate_app(was[0])

    def call(self, method: str, params: dict | None = None,
             session_id: str | None = None) -> dict:
        self._id += 1
        msg: dict = {"id": self._id, "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        self.ws.send_text(json.dumps(msg))
        while True:
            reply = json.loads(self.ws.recv_text())
            if reply.get("id") != self._id:
                continue                      # an event or another session's reply
            if "error" in reply:
                raise CDPError(f"{method}: {reply['error']}")
            return reply.get("result", {})

    def close(self) -> None:
        self.ws.close()
